"""Shared fixtures and helpers for agent-suite integration tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

# ---------------------------------------------------------------------------
# WI-075 meta-guard — the code under test must live in THIS repo
# ---------------------------------------------------------------------------
#
# In a freshly created worktree the project venv may lack pytest (the dev
# extra was never synced). `uv run pytest` then silently falls back to a
# PATH pytest whose site-packages can hold editable installs of suite
# components pointing at the PRIMARY checkout — tests collected from the
# worktree run against /projects/agent-suite's code, and "verified" claims
# are false in either direction. Same fails-open class as WI-026's silent
# skip: a green run that never exercised the change.
#
# The guard refuses to start the session unless ``agent_suite`` imports from
# under this repo root. Deliberately testing an installed distribution is the
# one legitimate exception — set AGENT_SUITE_TEST_INSTALLED=1 to say so.

REPO_ROOT = Path(__file__).resolve().parents[1]

_TEST_INSTALLED_ENV = "AGENT_SUITE_TEST_INSTALLED"


class CodeUnderTestError(RuntimeError):
    """The imported module does not come from the repo being tested."""


def require_code_under_test(
    repo_root: Path, module_file: str | None, module_name: str
) -> Path:
    """Prove ``module_name`` (imported from ``module_file``) lives under
    ``repo_root``; return the resolved module path.

    Pure so the falsifier tests in ``test_code_under_test_guard.py`` can
    exercise the deny case directly (process-calibration §5: a guard that
    cannot be shown to reject anything is a tautology).
    """
    if module_file is None:
        raise CodeUnderTestError(
            f"{module_name} has no __file__ — cannot prove which code is under test"
        )
    resolved = Path(module_file).resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        raise CodeUnderTestError(
            f"{module_name} imports from {resolved}, OUTSIDE the repo under test "
            f"({root}). You are almost certainly running a PATH pytest against "
            f"another checkout's code (WI-075). Fix: run "
            f"`uv run --frozen --extra dev pytest` from the repo root. To "
            f"deliberately test an installed distribution instead, set "
            f"{_TEST_INSTALLED_ENV}=1."
        )
    return resolved


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get(_TEST_INSTALLED_ENV) == "1":
        # Deliberate installed-dist mode — but an ambient export (e.g. in a
        # shell profile) would silently disable the guard for every session,
        # so say so loudly on every run it affects.
        import warnings

        warnings.warn(
            f"{_TEST_INSTALLED_ENV}=1: the WI-075 code-under-test guard is "
            "DISABLED for this session — tests may run against an installed "
            "distribution, not this checkout",
            stacklevel=1,
        )
        return
    import agent_suite

    try:
        require_code_under_test(
            REPO_ROOT, getattr(agent_suite, "__file__", None), "agent_suite"
        )
    except CodeUnderTestError as exc:
        raise pytest.UsageError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Prerequisite gating — building blocks for module-level skip decisions
# ---------------------------------------------------------------------------


def _regista_available() -> bool:
    try:
        import regista  # noqa: F401

        return True
    except ImportError:
        return False


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _dsn_available() -> bool:
    return bool(os.environ.get("INTEROP_DSN"))


def _can_run() -> bool:
    return _regista_available() and (_docker_available() or _dsn_available())


# ---------------------------------------------------------------------------
# Ephemeral Postgres via Docker
# ---------------------------------------------------------------------------


def _free_port() -> str:
    """Ask the kernel for an unused TCP port on the loopback interface.

    The port is released as soon as the socket closes, so the caller must bind
    it promptly and be prepared for the race — see ``_EphemeralPostgres.start``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


class _EphemeralPostgres:
    """Start/stop an ephemeral Postgres container for integration tests.

    The published port is allocated dynamically. A fixed port collides with
    any long-lived container the operator happens to be running (the suite's
    own ``agent-suite-smoke-pg`` sits on 5433), which failed the integration
    modules with a Docker exit-125 rather than a skip.
    """

    def __init__(self, container_name_prefix: str) -> None:
        self._container = f"{container_name_prefix}-{uuid.uuid4().hex[:8]}"
        self._port = _free_port()
        self._db = "interop"
        self._user = "interop"
        self._password = "interop_pw"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self._user}:{self._password}"
            f"@localhost:{self._port}/{self._db}"
        )

    def start(self, *, attempts: int = 5) -> None:
        """Run the container, re-drawing the port if the bind loses a race.

        ``_free_port`` closes the socket before Docker binds it, so another
        process can claim it in between. Docker exits 125 on that collision;
        retry with a fresh port rather than failing the whole module.
        """
        last_stderr = ""
        for attempt in range(attempts):
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self._container,
                    "-e",
                    f"POSTGRES_DB={self._db}",
                    "-e",
                    f"POSTGRES_USER={self._user}",
                    "-e",
                    f"POSTGRES_PASSWORD={self._password}",
                    "-p",
                    f"127.0.0.1:{self._port}:5432",
                    "postgres:16-alpine",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                self._wait_ready(timeout=30)
                return
            last_stderr = result.stderr.strip()
            # A failed `docker run --name` can still leave the name claimed.
            self.stop()
            if attempt < attempts - 1:
                self._port = _free_port()
        raise RuntimeError(
            f"Could not start {self._container} after {attempts} attempts: "
            f"{last_stderr}"
        )

    def _wait_ready(self, *, timeout: int = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(
                ["docker", "exec", self._container, "pg_isready", "-U", self._user],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"Postgres container {self._container} did not become ready within {timeout}s"
        )

    def stop(self) -> None:
        subprocess.run(
            ["docker", "rm", "-f", self._container],
            capture_output=True,
            text=True,
            check=False,
        )


# ---------------------------------------------------------------------------
# DSN helpers
# ---------------------------------------------------------------------------


class _InteropDsn:
    """Wrap a DSN string and expose host/port/db/user/password for pg_dump."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        parsed = urlparse(dsn)
        self.host = parsed.hostname or "localhost"
        self.port = str(parsed.port or 5432)
        self.db = parsed.path.lstrip("/") or "interop"
        self.user = parsed.username or "interop"
        self.password = parsed.password or "interop_pw"


# ---------------------------------------------------------------------------
# HMAC key generation
# ---------------------------------------------------------------------------


def _generate_hmac_key(path: Path, key_id: str = "test-hmac-key") -> None:
    """Write a minimal HMAC key-set JSON file for the test project."""
    key_data = {
        "keys": [
            {
                "key_id": key_id,
                "secret": base64.b64encode(secrets.token_bytes(32)).decode(),
                "status": "active",
            }
        ]
    }
    path.write_text(json.dumps(key_data))


def _generate_per_principal_ed25519_keys(
    path: Path, principal_ids: list[str]
) -> dict[str, dict[str, bytes]]:
    """Write a per-principal Ed25519 key-set file; return the raw key material.

    Each principal gets its own Ed25519 keypair bound by ``principal_id``.
    Returns the raw material ``{principal_id: {"secret": seed, "public":
    verify_key}}`` so a test can register the matching public key in the
    principal_keys registry (key_id is deterministic: ``f"ed-{principal_id}"``),
    making signing (key-set file) and binding verification (registry) agree.
    Mirrors ``regista`` 's ``tests/test_keys_multi_principal.json`` layout
    (Plan 022 P3).

    Requires PyNaCl (``regista[ed25519]``); callers guard with
    ``pytest.importorskip("nacl.signing")``.
    """
    import nacl.signing

    keys: list[dict[str, str]] = []
    material: dict[str, dict[str, bytes]] = {}
    for pid in principal_ids:
        signing_key = nacl.signing.SigningKey.generate()
        verify_key = signing_key.verify_key
        material[pid] = {
            "secret": bytes(signing_key),
            "public": bytes(verify_key),
        }
        keys.append(
            {
                "key_id": f"ed-{pid}",
                "principal_id": pid,
                "secret": base64.b64encode(bytes(signing_key)).decode("ascii"),
                "public_key": base64.b64encode(bytes(verify_key)).decode("ascii"),
                "encoding": "base64",
                "status": "active",
                "scheme": "ed25519",
                "alg": "Ed25519",
                "role": "actor",
            }
        )
    path.write_text(json.dumps({"keys": keys}))
    return material


# ---------------------------------------------------------------------------
# v6 epoch provisioning (WI-077)
# ---------------------------------------------------------------------------
#
# regista 0.6.0 is a hard cutover. A project store must contain exactly one v6
# ``project_initialized`` genesis event before ANY ordinary event, and every
# ordinary write is then funnelled through the v6 writer. The legacy recipe this
# conftest used — ``create_project`` with a shared HMAC key, then straight into
# ``create_work_item`` — is refused outright with
# ``[GENESIS_REQUIRED] project genesis must be written before ordinary events``.
#
# Four v6 properties the legacy recipe could not satisfy, and why each helper
# below exists:
#
# 1. **Ed25519, per-principal, actor-role keys.** ``_genesis._genesis_key``
#    requires ``scheme == "ed25519"``, ``role == "actor"``, ``status ==
#    "active"``, and ``entry.principal_id == actor.principal_id``; the v6 writer
#    repeats the last of those for every ordinary append
#    (``ACTOR_SIGNER_MISMATCH``). One shared HMAC key satisfies none of them, so
#    ``_generate_v6_keyset`` writes one keypair per principal.
#
# 2. **Canonical principal grammar.** ``actor.principal_id`` must be
#    ``(human|agent|service):<subject>`` (``TRUST-DOMAIN.md`` §2.1, enforced by
#    ``_verification._v6_require_principal_id``). The bare legacy names
#    ``test-agent`` / ``test-reviewer`` / ``test-acceptor`` are refused, so the
#    fixture's principals are now ``agent:test-agent``, ``human:test-reviewer``
#    and ``human:test-acceptor``.
#
# 3. **A key-binding anchor per principal.** Genesis embeds
#    ``bootstrap_key_acceptance`` for the *bootstrap* principal only. Every other
#    principal needs a standalone ``principal_key_accepted`` event, signed by the
#    bootstrap principal and anchored on the genesis event, before it may append
#    anything (``KEY_BINDING_UNRESOLVED`` otherwise). ``_v6_accept_key`` writes
#    those. There is no self-authorisation and no fallback to the
#    ``principal_keys`` projection (``TRUST-DOMAIN.md`` §5.11).
#
# 4. **A process-level producer identity.** ``_v6_writer.resolve_producer``
#    reads the harness from the environment and refuses an unset one with
#    ``LOAD_BEARING_FIELD_MISSING`` — it is deliberately not a per-append
#    argument (``V6-ENVELOPE.md`` §1.8). ``_set_v6_producer_env`` publishes it
#    through ``monkeypatch`` so it never leaks into the process environment of a
#    later test (or of the developer's shell).
#
# WHAT IS SYNTHETIC, AND WHY THAT IS SOUND. A genesis envelope names external
# trust references: ``trust_domain_core_digest``, ``genesis_document_digest``,
# ``trust_log_checkpoint`` and ``bootstrap_key_acceptance.trust_event_hash``.
# agent-suite has no trust log and no trust-domain document, so those values are
# fabricated here — deterministic digests over clearly-labelled ``agent-suite
# test-only`` strings (see ``_v6_test_digest``), never real root material.
#
# That is sound *because 0.6.0's genesis validation of those members is
# shape-only*: ``_genesis._validate_bootstrap_acceptance`` and its payload
# siblings check that each is a well-formed ``sha256:<64 hex>`` digest and that
# the checkpoint object has exactly the three expected members with
# ``checkpoint_seq >= 1``. Nothing resolves them against a trust log, and 0.6.0
# ships no resolver that could. The members 0.6.0 DOES cross-check are all real
# here and cannot be faked: ``bootstrap_key_acceptance.principal_id`` must equal
# ``actor.principal_id``, its ``key_id`` must equal ``signing.key_id``, its
# ``public_key`` must be the signing key's actual public bytes, and its
# ``fingerprint`` must be ``sha256`` of those bytes. So the fixture proves
# exactly what it can prove — key possession and chain integrity — and asserts
# nothing about external trust.
#
# If a later regista release starts *resolving* these references, this fixture
# must fail loudly rather than quietly keep passing; that is why the synthetic
# values are labelled in-band ("agent-suite test-only ...") instead of being
# plausible-looking hashes.

#: The bootstrap principal: the key that opens the epoch and accepts the other
#: principals' keys. A ``service:`` id because it is infrastructure — not a
#: person and not an agent (``RECONCILIATION.md`` Resolution 1).
V6_BOOTSTRAP_PRINCIPAL = "service:agent-suite-tests"

#: The three canonical actors the suite's integration tests drive the workflow
#: as. Same three roles as the legacy fixture, in the §2.1 grammar.
V6_AGENT_PRINCIPAL = "agent:test-agent"
V6_REVIEWER_PRINCIPAL = "human:test-reviewer"
V6_ACCEPTOR_PRINCIPAL = "human:test-acceptor"

#: The harness half of the producer block. True of the running process: these
#: events really are produced by agent-suite's test harness.
V6_PRODUCER_HARNESS = "agent-suite-tests"
V6_PRODUCER_HARNESS_VERSION = "conftest/1"

#: The reviewer lineage the fixture's ``adversarial_pass`` payloads declare.
#:
#: regista 0.6.0 (WI-307, ``REVIEW-VERDICTS.md`` §2.2 ingress amendment) makes
#: ``reviewer_claims.model_lineage`` MANDATORY for any positive review verdict
#: written inside the v6 epoch, and it must be a family in
#: ``_lineage.MODEL_LINEAGE_FAMILIES``. There is no "none" or "human" member, so
#: a verdict by a human reviewer cannot honestly omit it — see the WI-077 report
#: for the open question this raises. Fixture data for a fictional reviewer
#: principal; the *producer* block deliberately declares no model at all (below).
V6_REVIEWER_MODEL_LINEAGE = "claude-opus"

#: A distinct family for the fixture's *second* reviewer, where a test needs a
#: cross-lineage pass. Kept adjacent so the two can never accidentally be equal.
V6_SECOND_REVIEWER_MODEL_LINEAGE = "glm"


def _v6_test_digest(label: str) -> str:
    """A deterministic, self-labelling stand-in for an external trust digest.

    Deliberately derived from an in-band ``agent-suite test-only`` string rather
    than random bytes: the value is reproducible across runs (so a failure names
    a stable digest), and anyone who finds one of these in a store can tell at a
    glance that it is fixture material and not a real trust-log reference. See
    the section header for why a synthetic value is sound under 0.6.0's
    shape-only genesis validation.
    """
    seed = f"agent-suite test-only: {label}".encode()
    return "sha256:" + hashlib.sha256(seed).hexdigest()


@dataclass(frozen=True)
class V6TestKey:
    """One principal's Ed25519 actor key, with the derived v6 identifiers."""

    principal_id: str
    key_id: str
    seed: bytes
    public_key: bytes

    @property
    def fingerprint(self) -> str:
        return "ed25519:sha256:" + hashlib.sha256(self.public_key).hexdigest()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key).decode("ascii")


@dataclass(frozen=True)
class V6TestKeyset:
    """An Ed25519, actor-role, one-key-per-principal keyset on disk."""

    path: str
    keys: dict[str, V6TestKey]

    def key_for(self, principal_id: str) -> V6TestKey:
        try:
            return self.keys[principal_id]
        except KeyError:
            raise AssertionError(
                f"{principal_id!r} is not in this keyset. Pass it to "
                "_generate_v6_keyset rather than reusing another principal's key "
                "— the v6 writer refuses an actor/signer mismatch by design "
                "(ACTOR_SIGNER_MISMATCH)."
            ) from None


def _generate_v6_keyset(
    directory: Path,
    principals: tuple[str, ...],
    *,
    filename: str = "v6_keys.json",
) -> V6TestKeyset:
    """Write a fresh Ed25519 actor-role keyset covering ``principals``.

    Always into a caller-owned directory (``tmp_path``), never over a tracked
    fixture file. Requires PyNaCl, which regista 0.6.0 depends on unconditionally
    — callers already gate on ``_regista_available()``.
    """
    import nacl.signing

    keys: dict[str, V6TestKey] = {}
    entries: list[dict[str, Any]] = []
    for principal_id in principals:
        signing_key = nacl.signing.SigningKey.generate()
        key = V6TestKey(
            principal_id=principal_id,
            # Derived, not random, so a failure message is comparable between
            # runs and names which principal's key is involved.
            key_id="pk_" + hashlib.sha256(principal_id.encode()).hexdigest()[:16],
            seed=bytes(signing_key),
            public_key=bytes(signing_key.verify_key),
        )
        keys[principal_id] = key
        entries.append(
            {
                "key_id": key.key_id,
                "scheme": "ed25519",
                "alg": "Ed25519",
                "secret": base64.b64encode(key.seed).decode("ascii"),
                "encoding": "base64",
                "public_key": key.public_key_b64,
                "principal_id": principal_id,
                # The v6 writer requires role == "actor"; any other role is
                # refused with KEY_ROLE_NOT_PERMITTED.
                "role": "actor",
                "status": "active",
            }
        )
    target = directory / filename
    target.write_text(json.dumps({"keys": entries}, indent=2), encoding="utf-8")
    return V6TestKeyset(path=str(target), keys=keys)


def _set_v6_producer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish the process-level producer identity the v6 writer refuses without.

    Through ``monkeypatch`` rather than ``os.environ`` so it is undone at
    teardown: a leaked ``REGISTA_PRODUCER_*`` would silently satisfy
    ``resolve_producer`` for a later test that ought to be refused, and would
    escape into the developer's shell.

    ``model`` / ``model_lineage`` are deliberately DELETED rather than set. No
    model produces these events — a test harness does — and ``resolve_producer``
    treats both-absent as the legitimate "no model producer" case, distinct from
    "undeclared". Naming a real model here would be a signed falsehood, which is
    exactly what ``V6-ENVELOPE.md`` §1.8 exists to prevent. ``delenv`` also stops
    an ambient export in the developer's shell from leaking a model claim into
    every fixture-written event.
    """
    from regista._v6_writer import PRODUCER_ENV

    monkeypatch.setenv(PRODUCER_ENV["harness"], V6_PRODUCER_HARNESS)
    monkeypatch.setenv(PRODUCER_ENV["harness_version"], V6_PRODUCER_HARNESS_VERSION)
    monkeypatch.delenv(PRODUCER_ENV["model"], raising=False)
    monkeypatch.delenv(PRODUCER_ENV["model_lineage"], raising=False)


def _v6_genesis_envelope(
    keyset: V6TestKeyset,
    *,
    principal_id: str = V6_BOOTSTRAP_PRINCIPAL,
    entity_kinds: tuple[str, ...] = ("project", "principal", "workflow", "work_item"),
) -> dict[str, Any]:
    """Assemble a complete, valid ``project_initialized`` envelope.

    Hand-built rather than read from regista's committed
    ``tests/vectors/v6/bootstrap-project-initialized.json``: regista's ``tests/``
    package is not installed, so agent-suite cannot import or read it at run
    time. Every member below is therefore pinned against ``_genesis``'s
    validators, and ``occurred_at`` is taken at CALL time (never a module-import
    constant, which would drift arbitrarily far from the write).
    """
    from datetime import UTC, datetime

    from regista._v6_writer import resolve_producer

    key = keyset.key_for(principal_id)
    producer = resolve_producer()
    project_instance_id = str(uuid.uuid4())
    checkpoint = {
        "checkpoint_seq": 1,
        "head_event_hash": _v6_test_digest("trust log head"),
        "document_digest": _v6_test_digest("trust log document"),
    }
    return {
        "type": "regista.event",
        "version": 6,
        "event_id": str(uuid.uuid4()),
        "project_instance_id": project_instance_id,
        "trust_domain_id": str(uuid.uuid4()),
        # entity.id MUST equal project_instance_id, and entity_seq MUST be 1.
        "entity": {"kind": "project", "id": project_instance_id},
        "entity_seq": 1,
        "occurred_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "transition": "project_initialized",
        # Genesis names no workflow, takes the direct authorization mode with no
        # credentials, and has null predecessor links on both chains.
        "workflow": None,
        "actor": {"kind": "system", "principal_id": principal_id, "metadata": {}},
        "authorization": {"mode": "direct", "credentials": []},
        "chain": {
            "hash_algorithm": "sha-256",
            "previous_entity_event_hash": None,
            "previous_project_event_hash": None,
        },
        # key_binding_event_hash is null: genesis is the one Bootstrap-B position
        # regista permits, and its own bootstrap_key_acceptance below becomes the
        # project's first key-binding anchor.
        "signing": {
            "scheme_id": "ed25519",
            "key_id": key.key_id,
            "key_binding_event_hash": None,
        },
        "producer": {
            "harness": producer.harness,
            "harness_version": producer.harness_version,
            "model": producer.model,
            "model_lineage": producer.model_lineage,
        },
        "payload": {
            # --- synthetic, shape-validated only (see section header) ---
            "trust_domain_core_digest": _v6_test_digest("trust domain core"),
            "genesis_document_digest": _v6_test_digest("genesis document"),
            "trust_log_checkpoint": dict(checkpoint),
            # An empty previous epoch: a fixture-built project has no legacy
            # history, which is also why gate_passed=True is honest below.
            "previous_epoch": {
                "event_count": 0,
                "genesis_event_hash": None,
                "head_event_hash": None,
                "head_hash_construction": "sha256(canonical_envelope||signature)",
                "max_global_seq": None,
                "scheme_counts": {},
            },
            "bootstrap_key_acceptance": {
                # --- real, cross-checked against the signing key ---
                "principal_id": principal_id,
                "key_id": key.key_id,
                "scheme_id": "ed25519",
                "public_key": key.public_key_b64,
                "fingerprint": key.fingerprint,
                # --- synthetic, shape-validated only ---
                "trust_event_hash": _v6_test_digest("bootstrap key enrolment"),
                "trust_log_checkpoint": dict(checkpoint),
                "scopes": {
                    "entity_kinds": list(entity_kinds),
                    "transitions": None,
                    # may_accept_keys is what lets the bootstrap principal sign
                    # the standalone acceptances in _v6_accept_key; without it
                    # ordinary acceptance would have nowhere to start.
                    "may_accept_keys": True,
                    "may_sign_checkpoints": True,
                    "may_sign_bundles": False,
                },
            },
        },
    }


def _v6_accept_key(
    sub: Any,
    keyset: V6TestKeyset,
    genesis: Any,
    principal_id: str,
) -> Any:
    """Append the standalone ``principal_key_accepted`` for ``principal_id``.

    Signed by the bootstrap principal and anchored on the genesis event — never
    on itself. Until this runs, the v6 writer refuses ``principal_id`` with
    ``KEY_BINDING_UNRESOLVED``, and that refusal is correct: a key file is not a
    project-local acceptance.

    Reaches into ``regista._v6_writer`` because 0.6.0 exposes **no public
    key-acceptance API** — ``Regista`` has ``initialize_epoch`` for genesis and
    nothing for §5.8 acceptance, and ``regista.testing`` ships only the three
    ``seed_legacy_principal_key*`` helpers, which seed the legacy projection that
    §5.11 explicitly refuses as a v6 anchor. Flagged in the WI-077 report as a
    gap in regista's public surface, not a preference for private API.
    """
    from regista._v6_writer import (
        PRINCIPAL_KEY_ACCEPTED,
        append_v6_event,
        read_project_identity,
        resolve_producer,
    )

    key = keyset.key_for(principal_id)
    bootstrap = keyset.key_for(V6_BOOTSTRAP_PRINCIPAL)
    with sub._mgr.transaction() as conn:
        identity = read_project_identity(conn)
        assert identity is not None, "no v6 epoch is open on this project"
        payload = {
            "type": "regista.key-acceptance",
            "version": 1,
            "trust_domain_id": str(identity.trust_domain_id),
            "project_instance_id": str(identity.project_instance_id),
            "principal_id": principal_id,
            "key_id": key.key_id,
            "fingerprint": key.fingerprint,
            # public_key is repeated in the payload on purpose
            # (TRUST-DOMAIN.md §5.8): it makes a project bundle self-sufficient
            # for key MATERIAL without making it self-sufficient for TRUST.
            "public_key": key.public_key_b64,
            # Synthetic external referents, shape-validated only — same argument
            # as the genesis envelope's.
            "trust_event_hash": _v6_test_digest(f"key enrolment for {principal_id}"),
            "trust_log_checkpoint": {
                "checkpoint_seq": 1,
                "head_event_hash": _v6_test_digest("trust log head"),
                "document_digest": _v6_test_digest("trust log document"),
            },
            "scopes": {
                "entity_kinds": ["work_item", "principal", "workflow"],
                "transitions": None,
                "may_sign_checkpoints": False,
                "may_sign_bundles": False,
            },
            "accepted_by": {
                "principal_id": V6_BOOTSTRAP_PRINCIPAL,
                "key_id": bootstrap.key_id,
                "key_binding_event_hash": genesis.to_dict()["event_hash"],
            },
        }
        return append_v6_event(
            conn,
            sub._keys,
            entity_kind="principal",
            entity_id=uuid.uuid5(
                uuid.NAMESPACE_OID, "regista.principal:" + principal_id
            ),
            transition=PRINCIPAL_KEY_ACCEPTED,
            actor_id=V6_BOOTSTRAP_PRINCIPAL,
            actor_kind="system",
            producer=resolve_producer(),
            payload=payload,
        )


#: The closed §5.7 vocabulary a project-local acceptance revocation may cite.
#: Pinned here so a test cites a member rather than inventing a reason string,
#: which ``validate_key_acceptance_revocation_payload`` refuses outright.
V6_REVOCATION_REASONS = (
    "compromised",
    "superseded",
    "decommissioned",
    "policy",
    "unspecified",
)


def _v6_revoke_acceptance(
    sub: Any,
    keyset: V6TestKeyset,
    genesis: Any,
    acceptance: Any,
    principal_id: str,
    *,
    reason: str = "compromised",
) -> Any:
    """Append the ``principal_key_acceptance_revoked`` that ends a principal's
    authority to write, signed by the bootstrap principal.

    This is the v6 counterpart of the removed ``principals.revoke`` facade — and
    it is deliberately NOT a like-for-like replacement. Two differences matter to
    any test that used the old one:

    * **It is not retroactive.** ``TRUST-DOMAIN.md`` §5.10 step 4 refuses an
      event only when a revocation lies *between* the acceptance and that event
      on the project chain. Events written before the revocation keep verifying,
      because the acceptance really was valid when they were signed. The v5
      registry check was retroactive (revoke now, past events fail binding).
    * **It bites at write time.** After this, the principal's next append is
      refused with ``KEY_ACCEPTANCE_REVOKED``.

    Uses ``regista._v6_writer`` for the same reason ``_v6_accept_key`` does:
    0.6.0 exposes no public API for project-local acceptance or its revocation.
    """
    from regista._v6_writer import (
        PRINCIPAL_KEY_ACCEPTANCE_REVOKED,
        append_v6_event,
        read_project_identity,
        resolve_producer,
    )

    assert reason in V6_REVOCATION_REASONS, (
        f"{reason!r} is not in the closed §5.7 revocation vocabulary "
        f"{V6_REVOCATION_REASONS}; regista refuses the payload otherwise"
    )
    key = keyset.key_for(principal_id)
    bootstrap = keyset.key_for(V6_BOOTSTRAP_PRINCIPAL)
    with sub._mgr.transaction() as conn:
        identity = read_project_identity(conn)
        assert identity is not None, "no v6 epoch is open on this project"
        payload = {
            "type": "regista.key-acceptance-revocation",
            "version": 1,
            "trust_domain_id": str(identity.trust_domain_id),
            "project_instance_id": str(identity.project_instance_id),
            "principal_id": principal_id,
            "key_id": key.key_id,
            # A revocation names the exact acceptance it revokes so §5.10 step 4
            # decides by hash rather than guessing which acceptance was meant.
            "acceptance_event_hash": "sha256:" + acceptance.event_hash.hex(),
            "reason": reason,
            "revoked_by": {
                "principal_id": V6_BOOTSTRAP_PRINCIPAL,
                "key_id": bootstrap.key_id,
                "key_binding_event_hash": genesis.to_dict()["event_hash"],
            },
        }
        return append_v6_event(
            conn,
            sub._keys,
            entity_kind="principal",
            entity_id=uuid.uuid5(
                uuid.NAMESPACE_OID, "regista.principal:" + principal_id
            ),
            transition=PRINCIPAL_KEY_ACCEPTANCE_REVOKED,
            actor_id=V6_BOOTSTRAP_PRINCIPAL,
            actor_kind="system",
            producer=resolve_producer(),
            payload=payload,
        )


def _open_v6_epoch(
    sub: Any,
    keyset: V6TestKeyset,
    *,
    principals: tuple[str, ...],
) -> tuple[Any, dict[str, Any]]:
    """Open the project's v6 epoch and accept each of ``principals``.

    Returns ``(genesis, acceptances)``. The acceptance appends are returned
    rather than discarded because ``V6Append.event_hash`` is the *only* handle
    on them: the ``events`` table stores no ``event_hash`` column, so a caller
    that later needs to reference an acceptance (a revocation names its
    ``acceptance_event_hash``) cannot recover it by query.

    Order is the contract, not an implementation detail: genesis establishes the
    bootstrap key's authority, the standalone acceptances import that authority
    for the actor principals, and only then may an actor append anything.

    ``gate_passed=True`` is honest for a fixture-built project rather than a
    shortcut: the first-write gate exists to stop an operator opening an epoch
    over pre-existing legacy history, and a project created moments ago has
    none. ``principals`` is explicit rather than "every key in the keyset"
    because a helper that accepted every key on file would be blanket
    authorisation — the §5.11 property the writer exists to enforce.
    """
    genesis = sub.initialize_epoch(
        _v6_genesis_envelope(keyset), gate_passed=True
    )
    acceptances: dict[str, Any] = {}
    for principal_id in principals:
        if principal_id == V6_BOOTSTRAP_PRINCIPAL:
            continue
        acceptances[principal_id] = _v6_accept_key(
            sub, keyset, genesis, principal_id
        )
    return genesis, acceptances


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def interop_dsn() -> Generator[str, None, None]:
    """Provide a DSN to a Postgres instance for integration tests.

    If ``INTEROP_DSN`` is set (e.g. by a CI service container), use that.
    Otherwise stand up an ephemeral Docker container on a dynamically
    allocated port and tear it down after the module.
    """
    env_dsn = os.environ.get("INTEROP_DSN")
    if env_dsn:
        yield env_dsn
        return

    if not _can_run():
        pytest.skip(
            "Integration prerequisites not met — need regista + Docker or INTEROP_DSN"
        )

    pg = _EphemeralPostgres(container_name_prefix="agent-suite-interop")
    pg.start()
    try:
        yield pg.dsn
    finally:
        pg.stop()


@dataclass
class RegistaProject:
    """A provisioned regista project with an open v6 epoch, workflow and roles."""

    sub: Any  # regista.Regista — imported lazily to keep conftest loadable
    project: str
    key_path: str
    agent: str
    reviewer: str
    acceptor: str
    agent_meta: dict[str, str]
    human_meta: dict[str, str]
    dsn: str
    # --- v6 epoch additions (WI-077) ---
    #: The ``service:`` principal that opened the epoch and accepted the three
    #: actor keys. Exposed because a test that appends its own event outside the
    #: canonical workflow needs a principal whose key-binding anchor is genesis.
    bootstrap: str
    #: The Ed25519 keyset backing the project, so a test can sign or verify
    #: under a principal's actual key material.
    keyset: V6TestKeyset
    #: The genesis write (``V6GenesisWrite``), whose ``event_hash`` is the
    #: project's first key-binding anchor.
    genesis: Any
    #: ``{principal_id: V6Append}`` for each actor's standalone
    #: ``principal_key_accepted``. Kept because ``V6Append.event_hash`` is the
    #: only handle on those events — the ``events`` table has no ``event_hash``
    #: column, so an acceptance cannot be referenced by query after the fact.
    acceptances: dict[str, Any]

    @property
    def reviewer_claims(self) -> dict[str, str]:
        """The mandatory ``reviewer_claims`` block for a v6 positive verdict.

        A property rather than a stored dict so each call site gets its own copy
        and cannot mutate the fixture's for the next one.
        """
        return {"model_lineage": V6_REVIEWER_MODEL_LINEAGE}

    def review_payload(self, note: str, **extra: Any) -> dict[str, Any]:
        """A complete ``adversarial_pass`` payload: review note + reviewer claims.

        Exists so no test has to remember that WI-307 made ``reviewer_claims``
        mandatory inside the epoch — omitting it fails closed at ingress with
        ``INVALID_MODEL_LINEAGE``, which reads like a fixture bug rather than the
        contract it is.
        """
        return {"review_note": note, "reviewer_claims": self.reviewer_claims, **extra}

    def revoke_acceptance(
        self, principal_id: str, *, reason: str = "compromised"
    ) -> Any:
        """Revoke ``principal_id``'s project-local key acceptance.

        See ``_v6_revoke_acceptance`` for what this does and does NOT do — in
        particular it is not retroactive, which is where it parts company with
        the v5 ``principals.revoke`` it replaces.
        """
        return _v6_revoke_acceptance(
            self.sub,
            self.keyset,
            self.genesis,
            self.acceptances[principal_id],
            principal_id,
            reason=reason,
        )


@pytest.fixture
def regista_project(
    interop_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[RegistaProject, None, None]:
    """A fresh regista project with an OPEN v6 epoch, the canonical workflow and
    3 accepted actor principals.

    Under regista 0.6.0 this is no longer "create a project and write events":
    the store must be taken across the v6 epoch boundary first, and the order
    below is load-bearing. See the ``v6 epoch provisioning`` section above for
    what each step satisfies and which values are synthetic.
    """
    if not _regista_available():
        # In CI (INTEROP_REQUIRE_FACES=1) a missing spine is an install
        # regression, not an optional proof — fail instead of skipping, so the
        # adversarial corpus cannot silently regress to a skip (Plan 002 WI-2).
        if os.environ.get("INTEROP_REQUIRE_FACES", "").strip().lower() in {"1", "true", "yes"}:
            pytest.fail(
                "INTEROP_REQUIRE_FACES=1 is set but regista is not importable — "
                "verify the spine-install step in CI."
            )
        pytest.skip("regista is not installed")

    import regista as regista_pkg
    from regista import Regista
    from regista.testing import drop_project_schema

    project = f"conftest_{uuid.uuid4().hex[:8]}"
    agent = V6_AGENT_PRINCIPAL
    reviewer = V6_REVIEWER_PRINCIPAL
    acceptor = V6_ACCEPTOR_PRINCIPAL
    actors = (agent, reviewer, acceptor)

    # The writer resolves the producer from the environment at append time, so
    # this must be in place before the first write — including genesis, whose
    # envelope producer block is built from the same resolution.
    _set_v6_producer_env(monkeypatch)

    keyset = _generate_v6_keyset(tmp_path, (V6_BOOTSTRAP_PRINCIPAL, *actors))

    sub = Regista.create_project(interop_dsn, project, keyset.path)
    try:
        # Genesis FIRST. register_workflow is epoch-aware: post-genesis it also
        # appends the signed ``workflow_registered`` event that admission gate 1
        # resolves (a workflow_registry row is not a registration,
        # V6-ENVELOPE.md §1.9), so registering before genesis would leave the
        # row without its event and every workflow-naming append refused.
        genesis, acceptances = _open_v6_epoch(sub, keyset, principals=actors)
        sub.register_workflow(regista_pkg.canonical_workflow_yaml())
        sub.register_actor_role(agent, "agent")
        sub.register_actor_role(reviewer, "human")
        sub.register_actor_role(acceptor, "human")

        yield RegistaProject(
            sub=sub,
            project=project,
            key_path=keyset.path,
            agent=agent,
            reviewer=reviewer,
            acceptor=acceptor,
            agent_meta={"role": "agent"},
            human_meta={"role": "human"},
            dsn=interop_dsn,
            bootstrap=V6_BOOTSTRAP_PRINCIPAL,
            keyset=keyset,
            genesis=genesis,
            acceptances=acceptances,
        )
    finally:
        sub.close()
        drop_project_schema(interop_dsn, project)
