"""Per-user identity lifecycle — onboarding and offboarding (Plan 001 WI-3.3).

``docs/multi-user-onboarding.md`` §3 specifies joining (write a per-user
``suite.env`` overlay + provision the principal's signing key) and §6
specifies leaving (revoke the principal's keys, then remove the private key
from the secret backend). The documented contract existed; the code did not —
bootstrap step 7 reported "not yet implemented" and there was no leaver path
at all.

Design (AGENTS.md): thin orchestration. Every irreversible act is regista's
own CLI verb (``regista principal enroll`` / ``list`` / ``revoke``); this
module owns only the ordering, the overlay file, and honest reporting. The
runner and installed-check are injectable (the ``doctor.py`` / ``bootstrap.py``
pattern) so tests drive the full lifecycle against a stubbed regista with no
live store.

Offboarding revokes the key (the SLA-bearing act, which windows it out of the
registry) *and* deletes the custodied private key, so the fetch path closes
too. Where deletion is genuinely impossible — a backend that refuses, or a
reference that carries the secret inline rather than pointing at it — the run
reports ``MANUAL`` with the exact refs, never folding it into success.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, assert_never

from agent_suite.component_result import ChildOutcome, evaluate_component_result
from agent_suite.config import _parse_env_file, user_suite_env_path

# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as bootstrap.Runner / bootstrap.Installed)
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a component CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
# Closed-set enums (assert_never in every dispatch)
# ---------------------------------------------------------------------------


class IdentityAction(Enum):
    """Which half of the lifecycle ran."""

    ONBOARD = "onboard"
    OFFBOARD = "offboard"


class IdentityOutcome(Enum):
    """The outcome of one step, and of the run as a whole.

    ``MANUAL`` is the honest seam: the suite did everything it can do and an
    operator action remains. It is distinct from ``DONE`` so that automation
    cannot read a half-finished offboarding as complete.
    """

    DONE = "done"
    ALREADY_DONE = "already_done"
    PENDING = "pending"
    MANUAL = "manual_action_required"
    REFUSED = "refused"
    FAILED = "failed"


# Worst-first: the aggregate outcome is the first of these any step reports.
_OUTCOME_PRECEDENCE: tuple[IdentityOutcome, ...] = (
    IdentityOutcome.FAILED,
    IdentityOutcome.REFUSED,
    IdentityOutcome.MANUAL,
    IdentityOutcome.PENDING,
    IdentityOutcome.DONE,
    IdentityOutcome.ALREADY_DONE,
)


def outcome_is_success(outcome: IdentityOutcome) -> bool:
    """True when the outcome needs no further action to be correct."""
    match outcome:
        case IdentityOutcome.DONE | IdentityOutcome.ALREADY_DONE | IdentityOutcome.PENDING:
            return True
        case IdentityOutcome.MANUAL | IdentityOutcome.REFUSED | IdentityOutcome.FAILED:
            return False
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityStep:
    """One step of the lifecycle."""

    name: str
    outcome: IdentityOutcome
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IdentityResult:
    """The whole run: every step, plus the worst outcome among them."""

    action: IdentityAction
    principal: str
    outcome: IdentityOutcome
    steps: tuple[IdentityStep, ...]

    @property
    def ok(self) -> bool:
        return outcome_is_success(self.outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action.value,
            "principal": self.principal,
            "outcome": self.outcome.value,
            "steps": [s.to_dict() for s in self.steps],
        }


def aggregate_outcome(steps: tuple[IdentityStep, ...]) -> IdentityOutcome:
    """Reduce step outcomes to one, worst-first."""
    if not steps:
        return IdentityOutcome.ALREADY_DONE
    reported = {s.outcome for s in steps}
    for candidate in _OUTCOME_PRECEDENCE:
        if candidate in reported:
            return candidate
    raise AssertionError(f"unreduced outcomes: {reported}")


# ---------------------------------------------------------------------------
# The per-user suite.env overlay (bootstrap-contract §2, onboarding doc §3)
# ---------------------------------------------------------------------------


_OVERLAY_HEADER = (
    "# Per-user overlay — written by `agent-suite bootstrap --user <principal>`.\n"
    "# Layers on top of the system suite.env; process env still wins.\n"
    "# Shared facts (DSN, secret backend) stay in the system file.\n"
)

PRINCIPAL_KEY = "REGISTA_PRINCIPAL_ID"
PROJECT_KEY = "AGENT_NOTES_PROJECT"
PROJECTS_KEY = "DOSSIER_PROJECTS"


def overlay_values(
    principal: str,
    *,
    project: str | None = None,
    projects: tuple[str, ...] = (),
) -> dict[str, str]:
    """The keys this suite owns in a per-user overlay."""
    values = {PRINCIPAL_KEY: principal}
    if project:
        values[PROJECT_KEY] = project
    if projects:
        values[PROJECTS_KEY] = ",".join(projects)
    return values


def render_overlay(values: dict[str, str]) -> str:
    """Render an overlay file body — stable order, so re-runs are no-ops."""
    lines = [_OVERLAY_HEADER]
    lines.extend(f"{key}={values[key]}\n" for key in sorted(values))
    return "".join(lines)


def write_overlay(
    path: Path,
    values: dict[str, str],
    *,
    dry_run: bool = False,
) -> IdentityStep:
    """Merge ``values`` into the overlay at ``path``.

    Keys the suite does not own are preserved. Re-running with the same inputs
    rewrites byte-identical content and reports ``ALREADY_DONE``, so the step
    is idempotent in the sense the bootstrap contract requires.
    """
    existing = _parse_env_file(path)
    merged = {**existing, **values}
    body = render_overlay(merged)
    if path.is_file() and path.read_text(encoding="utf-8") == body:
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.ALREADY_DONE,
            f"overlay at {path} already current",
        )
    if dry_run:
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.PENDING,
            f"would write overlay at {path} ({', '.join(sorted(values))})",
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError as exc:
        return IdentityStep(
            "user_overlay", IdentityOutcome.FAILED, f"could not write {path}: {exc}"
        )
    return IdentityStep(
        "user_overlay", IdentityOutcome.DONE, f"overlay written at {path}"
    )


def remove_overlay(path: Path, *, dry_run: bool = False) -> IdentityStep:
    """Delete a per-user overlay (leaver path)."""
    if not path.is_file():
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.ALREADY_DONE,
            f"no overlay at {path}",
        )
    if dry_run:
        return IdentityStep(
            "user_overlay", IdentityOutcome.PENDING, f"would remove overlay at {path}"
        )
    try:
        path.unlink()
    except OSError as exc:
        return IdentityStep(
            "user_overlay", IdentityOutcome.FAILED, f"could not remove {path}: {exc}"
        )
    return IdentityStep(
        "user_overlay", IdentityOutcome.DONE, f"overlay removed at {path}"
    )


# ---------------------------------------------------------------------------
# regista principal verbs
# ---------------------------------------------------------------------------


def _run_regista(
    runner: Runner, cmd: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str] | None, str]:
    """Run a regista command; return (result, error-detail-if-it-could-not-run)."""
    try:
        return runner(cmd), ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, str(exc)


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _enroll_principal(
    *,
    runner: Runner,
    principal: str,
    secret_backend: str | None,
    dry_run: bool,
    key_path: str | None = None,
) -> IdentityStep:
    # `--json` is a *global* regista flag and must precede the subcommand:
    # the `principal` subcommands do not define their own (unlike `provision`),
    # so a trailing --json is rejected as an unrecognised argument.
    #
    # `--hmac-key-path` is passed explicitly for the same reason it is global:
    # `principal enroll` resolves the key file through regista's own config and,
    # on a host where `REGISTA_KEY_PATH` is set only in `suite.env`, fails with
    # `[UNKNOWN_KEY_ID] hmac_key_path is required`. Measured on the qualification
    # host: identical command plus this flag returns `already_existed: true`.
    cmd: tuple[str, ...] = ("regista", "--json")
    if key_path:
        cmd += ("--hmac-key-path", key_path)
    cmd += ("principal", "enroll", "--principal", principal)
    if secret_backend:
        cmd += ("--secret-backend", secret_backend)
    if dry_run:
        return IdentityStep(
            "principal_key",
            IdentityOutcome.PENDING,
            f"would run {' '.join(cmd)}",
        )
    result, run_error = _run_regista(runner, cmd)
    if result is None:
        return IdentityStep(
            "principal_key", IdentityOutcome.FAILED, f"enroll failed: {run_error}"
        )
    # regista refuses rather than overwriting an existing key. That refusal is
    # recognised by its error *code* — the previous substring match on
    # "clobber"/"refuse" made regista's prose part of this contract (WI-051).
    verdict = evaluate_component_result(
        command=f"regista principal enroll --principal {principal}",
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        require_fields=("key_id", "already_existed", "secret_backend"),
    )
    match verdict.outcome:
        case ChildOutcome.REFUSED:
            return IdentityStep(
                "principal_key",
                IdentityOutcome.REFUSED,
                f"enroll refused (nothing was clobbered): {verdict.detail}",
            )
        case ChildOutcome.FAILED:
            return IdentityStep(
                "principal_key", IdentityOutcome.FAILED, f"enroll failed: {verdict.detail}"
            )
        case ChildOutcome.SUCCESS:
            pass
        case other:
            assert_never(other)
    key_id = verdict.field("key_id")
    backend = verdict.field("secret_backend")
    if verdict.field("already_existed") is True:
        return IdentityStep(
            "principal_key",
            IdentityOutcome.ALREADY_DONE,
            f"principal {principal} already has active key {key_id} ({backend})",
        )
    return IdentityStep(
        "principal_key",
        IdentityOutcome.DONE,
        f"enrolled key {key_id} for {principal} in {backend}",
    )


def _active_keys(
    *, runner: Runner, principal: str
) -> tuple[list[dict[str, Any]], IdentityStep | None]:
    """List a principal's active keys. Returns (keys, failure-step-or-None)."""
    cmd: tuple[str, ...] = (
        "regista", "--json", "principal", "list",
        "--principal", principal,
        "--status", "active",
    )
    result, run_error = _run_regista(runner, cmd)
    if result is None:
        return [], IdentityStep(
            "revoke_keys", IdentityOutcome.FAILED, f"principal list failed: {run_error}"
        )
    if result.returncode != 0:
        return [], IdentityStep(
            "revoke_keys",
            IdentityOutcome.FAILED,
            f"principal list failed: {result.stderr.strip() or 'no detail'}",
        )
    data = _parse_json(result.stdout)
    if not isinstance(data, list):
        return [], IdentityStep(
            "revoke_keys",
            IdentityOutcome.FAILED,
            "principal list --json emitted no JSON array on stdout",
        )
    return [entry for entry in data if isinstance(entry, dict)], None


def _revoke_keys(
    *,
    runner: Runner,
    principal: str,
    reason: str,
    dry_run: bool,
) -> tuple[IdentityStep, list[dict[str, Any]]]:
    """Revoke every active key for ``principal``. Returns (step, revoked-entries)."""
    keys, failure = _active_keys(runner=runner, principal=principal)
    if failure is not None:
        return failure, []
    if not keys:
        return (
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.ALREADY_DONE,
                f"principal {principal} has no active keys",
            ),
            [],
        )
    key_ids = [str(k.get("key_id", "")) for k in keys if k.get("key_id")]
    if dry_run:
        return (
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.PENDING,
                f"would revoke {len(key_ids)} active key(s): {', '.join(key_ids)}",
            ),
            keys,
        )
    revoked: list[dict[str, Any]] = []
    for entry, key_id in zip(keys, key_ids, strict=True):
        cmd: tuple[str, ...] = (
            "regista", "--json", "principal", "revoke",
            "--principal", principal,
            "--key-id", key_id,
            "--reason", reason,
        )
        result, run_error = _run_regista(runner, cmd)
        if result is None or result.returncode != 0:
            detail = run_error or (result.stderr.strip() if result else "")
            # Report what did land — a half-revoked principal is exactly the
            # state an operator must not mistake for a clean offboarding.
            return (
                IdentityStep(
                    "revoke_keys",
                    IdentityOutcome.FAILED,
                    f"revoked {len(revoked)}/{len(key_ids)} keys; "
                    f"{key_id} failed: {detail or 'no detail'}",
                ),
                revoked,
            )
        revoked.append(entry)
    return (
        IdentityStep(
            "revoke_keys",
            IdentityOutcome.DONE,
            f"revoked {len(revoked)} key(s): {', '.join(key_ids)}",
        ),
        revoked,
    )


def _secret_backend_step(
    revoked: list[dict[str, Any]],
    *,
    runner: Runner,
    dry_run: bool,
) -> IdentityStep:
    """Remove the custodied private keys, so the fetch path actually closes.

    Revocation windows the key out of the registry (onboarding doc §6) but
    leaves the private key readable from the backend; deleting it is what
    finishes the job. ``regista secrets --delete`` is idempotent, so a re-run
    of an offboarding is safe.

    Two outcomes are not deletions and are reported as ``MANUAL`` rather than
    folded into success: a backend that refuses (``env:``), and a reference
    that *carries* the secret rather than pointing at it (``windows:``,
    ``literal:``) — there the operator has to discard the reference itself,
    because every copy of it is a copy of the key.
    """
    refs = sorted(
        {
            str(entry["secret_ref"])
            for entry in revoked
            if isinstance(entry.get("secret_ref"), str) and entry["secret_ref"]
        }
    )
    if not refs:
        return IdentityStep(
            "secret_backend",
            IdentityOutcome.ALREADY_DONE,
            "no custodied private-key refs recorded for the revoked keys",
        )
    if dry_run:
        return IdentityStep(
            "secret_backend",
            IdentityOutcome.PENDING,
            f"would delete {len(refs)} custodied private key(s): {', '.join(refs)}",
        )

    deleted: list[str] = []
    inline: list[str] = []
    failed: list[str] = []
    for ref in refs:
        cmd: tuple[str, ...] = ("regista", "--json", "secrets", "--ref", ref, "--delete")
        result, run_error = _run_regista(runner, cmd)
        if result is None or result.returncode != 0:
            failed.append(f"{ref} ({run_error or 'delete refused'})")
            continue
        data = _parse_json(result.stdout)
        outcome = data.get("outcome") if isinstance(data, dict) else None
        if outcome in ("deleted", "already_absent"):
            deleted.append(ref)
        else:
            inline.append(ref)

    parts: list[str] = []
    if deleted:
        parts.append(f"deleted {len(deleted)} custodied key(s)")
    if inline:
        parts.append(
            f"{len(inline)} reference(s) carry the key inline and must be "
            f"discarded wherever they are recorded: {', '.join(inline)}"
        )
    if failed:
        parts.append(f"could not delete: {', '.join(failed)}")

    if failed or inline:
        return IdentityStep(
            "secret_backend", IdentityOutcome.MANUAL, "; ".join(parts)
        )
    return IdentityStep("secret_backend", IdentityOutcome.DONE, "; ".join(parts))


# ---------------------------------------------------------------------------
# The dossier identity binding (WI-052)
#
# dossier WI-035 made a human's transitions sign under a **per-actor** Ed25519
# key, and it keys that on an explicit ``principal_id`` recorded on the dossier
# identity. It never derives one — not from the username, not from the
# stable_id — because a derived binding would claim a signing identity the
# suite may not have provisioned.
#
# `bootstrap --user <principal_id>` provisioned the key and wrote the overlay
# and stopped there, so a by-the-book onboarding still left the human
# unattributable: their acceptance was either refused (the prod default) or
# downgraded to the shared store HMAC key. That is exactly how the
# qualification run failed — users.json had username "qual-human" and the
# provisioned principal was "qual-human", and nothing joined those two facts.
# ---------------------------------------------------------------------------

#: Where dossier's local backend reads identities from.
DOSSIER_USERS_PATH_ENV = "DOSSIER_USERS_PATH"
#: Which identity source dossier is configured with (``local`` | ``ldap``).
DOSSIER_BACKEND_ENV = "DOSSIER_AUTH_BACKEND"
#: The directory attribute carrying the principal id on the LDAP backend.
DOSSIER_LDAP_ATTR_ENV = "DOSSIER_LDAP_PRINCIPAL_ID_ATTR"

#: The field dossier reads the binding from, on the user's users.json entry.
DOSSIER_BINDING_FIELD = "principal_id"

BINDING_STEP = "dossier_binding"

# Mirrors dossier's ``keys._validate_principal_id``: an invalid principal_id
# fails at *load* for the local backend, so writing one would take dossier's
# whole identity source down rather than fail this step.
_PRINCIPAL_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_PRINCIPAL_ID_MAX_LEN = 256


def principal_id_problem(principal: str) -> str | None:
    """Why ``principal`` is not a usable regista/dossier principal id."""
    if not principal:
        return "principal_id is required"
    if len(principal) > _PRINCIPAL_ID_MAX_LEN:
        return f"principal_id must be at most {_PRINCIPAL_ID_MAX_LEN} characters"
    if not _PRINCIPAL_ID_RE.match(principal):
        return (
            "principal_id must be alphanumeric, dot, hyphen, or underscore only"
        )
    return None


def _ldap_binding_step(env: Mapping[str, str], principal: str) -> IdentityStep:
    """The LDAP backend's binding is a directory write the suite cannot do."""
    attr = env.get(DOSSIER_LDAP_ATTR_ENV, "").strip()
    if attr:
        detail = (
            f"dossier reads the binding from the directory attribute {attr!r} "
            f"({DOSSIER_LDAP_ATTR_ENV}); populate it with {principal!r} for this "
            f"human in the directory. The suite cannot write to the directory, "
            f"and `dossier doctor`'s human_signing check is what confirms it"
        )
    else:
        detail = (
            f"{DOSSIER_LDAP_ATTR_ENV} is not set, so every LDAP identity is "
            f"unbound and no human can sign per-actor. Set it to the attribute "
            f"carrying the suite principal id (often sAMAccountName) and "
            f"populate that attribute with {principal!r} for this human"
        )
    return IdentityStep(BINDING_STEP, IdentityOutcome.MANUAL, detail)


def _load_users(path: Path) -> tuple[list[dict[str, Any]] | None, str]:
    """Read dossier's users file. Returns ``(users, error-detail)``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not read {path}: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON: {exc}"
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        return None, f"{path} must be a JSON array of user objects"
    return [dict(entry) for entry in data], ""


def _write_users(path: Path, users: list[dict[str, Any]]) -> str:
    """Rewrite dossier's users file atomically. Returns an error detail or ""."""
    try:
        mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".users_", suffix=".tmp"
        )
    except OSError as exc:
        return f"could not create a temporary file beside {path}: {exc}"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(users, handle, indent=2)
            handle.write("\n")
        # The file carries password hashes: keep whatever mode the operator set
        # rather than widening or narrowing it as a side effect.
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return f"could not write {path}: {exc}"
    return ""


def bind_dossier_identity(
    *,
    principal: str,
    env: Mapping[str, str],
    dossier_user: str | None = None,
    installed: Installed,
    dry_run: bool = False,
) -> IdentityStep:
    """Record ``principal`` as the regista principal of a dossier identity.

    Idempotent, like the key step: an identity already bound to this principal
    reports ``ALREADY_DONE``. An identity bound to a *different* principal is
    ``REFUSED`` rather than rewritten — rebinding changes the actor_id a human
    signs under, which splits their history at the changeover (dossier
    `docs/deploy.md` §5) and is not something onboarding should do silently.
    """
    problem = principal_id_problem(principal)
    if problem is not None:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.FAILED,
            f"cannot bind {principal!r}: {problem}",
        )

    backend = env.get(DOSSIER_BACKEND_ENV, "").strip().lower() or "local"
    users_path_raw = env.get(DOSSIER_USERS_PATH_ENV, "").strip()

    if not installed("dossier") and not users_path_raw:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.ALREADY_DONE,
            "dossier is not installed and no identity source is configured on "
            "this host; there is no dossier identity to bind",
        )

    if backend == "ldap":
        return _ldap_binding_step(env, principal)
    if backend != "local":
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.FAILED,
            f"{DOSSIER_BACKEND_ENV}={backend!r} is not a dossier identity "
            f"backend (expected 'local' or 'ldap')",
        )

    if not users_path_raw:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.MANUAL,
            f"{DOSSIER_USERS_PATH_ENV} is not set, so the suite cannot record "
            f"the {DOSSIER_BINDING_FIELD} dossier needs to find this human's "
            f"per-actor signing key; set it and re-run, or add "
            f'"{DOSSIER_BINDING_FIELD}": "{principal}" to their users.json entry',
        )

    users_path = Path(users_path_raw).expanduser()
    username = (dossier_user or principal).strip()
    if dry_run:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.PENDING,
            f"would record {DOSSIER_BINDING_FIELD}={principal} on the "
            f"{username!r} entry in {users_path}",
        )

    users, load_error = _load_users(users_path)
    if users is None:
        return IdentityStep(BINDING_STEP, IdentityOutcome.FAILED, load_error)

    matches = [
        entry
        for entry in users
        if str(entry.get("username", "")).strip().lower() == username.lower()
    ]
    if not matches:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.MANUAL,
            f"no dossier identity with username {username!r} in {users_path}, "
            f"so nothing records that {principal!r} is their signing principal. "
            f"Create their dossier user and re-run, pass the username "
            f"explicitly if it differs from the principal id, or ignore this "
            f"for a non-human principal that never acts through dossier",
        )
    if len(matches) > 1:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.FAILED,
            f"{users_path} has {len(matches)} entries with username "
            f"{username!r}; cannot tell which identity to bind",
        )

    entry = matches[0]
    existing = entry.get(DOSSIER_BINDING_FIELD)
    if isinstance(existing, str) and existing.strip() == principal:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.ALREADY_DONE,
            f"{username!r} in {users_path} is already bound to principal "
            f"{principal!r}",
        )
    if isinstance(existing, str) and existing.strip():
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.REFUSED,
            f"{username!r} in {users_path} is already bound to principal "
            f"{existing.strip()!r}, not {principal!r}. Rebinding changes the "
            f"actor_id this human signs under and splits their history at the "
            f"changeover, so it is an explicit operator decision — edit the "
            f"entry deliberately if that is what you intend",
        )

    entry[DOSSIER_BINDING_FIELD] = principal
    write_error = _write_users(users_path, users)
    if write_error:
        return IdentityStep(BINDING_STEP, IdentityOutcome.FAILED, write_error)
    return IdentityStep(
        BINDING_STEP,
        IdentityOutcome.DONE,
        f"bound dossier identity {username!r} to principal {principal!r} in "
        f"{users_path}; the human must re-authenticate before their session "
        f"carries the new actor_id",
    )


def unbind_dossier_identity(
    *,
    principal: str,
    env: Mapping[str, str],
    dossier_user: str | None = None,
    installed: Installed,
    dry_run: bool = False,
) -> IdentityStep:
    """Remove a leaver's binding, so it does not point at a revoked principal.

    Not a security hole either way — the key is revoked and deleted, and dossier
    refuses to fall back to the store key — but a binding pointing at nothing
    reads as a provisioning failure rather than a leaver (WI-052 ask 3).
    """
    backend = env.get(DOSSIER_BACKEND_ENV, "").strip().lower() or "local"
    users_path_raw = env.get(DOSSIER_USERS_PATH_ENV, "").strip()
    if backend == "ldap":
        attr = env.get(DOSSIER_LDAP_ATTR_ENV, "").strip() or DOSSIER_LDAP_ATTR_ENV
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.MANUAL,
            f"clear the {attr} attribute for this leaver in the directory; the "
            f"suite cannot write to it",
        )
    if not users_path_raw:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.ALREADY_DONE,
            f"{DOSSIER_USERS_PATH_ENV} is not set; no local dossier binding to remove",
        )
    users_path = Path(users_path_raw).expanduser()
    username = (dossier_user or principal).strip()
    users, load_error = _load_users(users_path)
    if users is None:
        return IdentityStep(BINDING_STEP, IdentityOutcome.FAILED, load_error)
    bound = [
        entry
        for entry in users
        if str(entry.get(DOSSIER_BINDING_FIELD, "")).strip() == principal
        or str(entry.get("username", "")).strip().lower() == username.lower()
    ]
    stale = [
        entry
        for entry in bound
        if str(entry.get(DOSSIER_BINDING_FIELD, "")).strip() == principal
    ]
    if not stale:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.ALREADY_DONE,
            f"no dossier identity in {users_path} is bound to {principal!r}",
        )
    if dry_run:
        return IdentityStep(
            BINDING_STEP,
            IdentityOutcome.PENDING,
            f"would remove the {DOSSIER_BINDING_FIELD}={principal} binding from "
            f"{len(stale)} identity/identities in {users_path}",
        )
    for entry in stale:
        entry.pop(DOSSIER_BINDING_FIELD, None)
    write_error = _write_users(users_path, users)
    if write_error:
        return IdentityStep(BINDING_STEP, IdentityOutcome.FAILED, write_error)
    return IdentityStep(
        BINDING_STEP,
        IdentityOutcome.DONE,
        f"removed the {principal!r} binding from {len(stale)} dossier "
        f"identity/identities in {users_path}",
    )


# ---------------------------------------------------------------------------
# The two lifecycle entry points
# ---------------------------------------------------------------------------


def run_user_onboarding(
    *,
    principal: str,
    project: str | None = None,
    projects: tuple[str, ...] = (),
    overlay_path: Path | None = None,
    secret_backend: str | None = None,
    dry_run: bool = False,
    runner: Runner | None = None,
    installed: Installed | None = None,
    env: Mapping[str, str] | None = None,
    dossier_user: str | None = None,
) -> IdentityResult:
    """Onboard one human or agent principal (onboarding doc §3).

    Three steps, all idempotent: the per-user overlay, the principal's signing
    key (never overwritten), and the **dossier identity binding** that makes the
    key usable for a human's transitions. Without the third, a human whose
    onboarding followed every documented step still had no ``principal_id`` on
    their dossier identity, so dossier could not find their key and either
    refused their acceptance or downgraded it to the shared store key (WI-052).
    """
    run = runner or _default_runner
    is_installed = installed or _default_installed
    path = overlay_path or user_suite_env_path()
    resolved_env: Mapping[str, str] = os.environ if env is None else env

    steps: list[IdentityStep] = [
        write_overlay(
            path,
            overlay_values(principal, project=project, projects=projects),
            dry_run=dry_run,
        )
    ]

    if not is_installed("regista"):
        steps.append(
            IdentityStep(
                "principal_key",
                IdentityOutcome.FAILED,
                "regista not installed — cannot provision the principal's signing key",
            )
        )
    else:
        steps.append(
            _enroll_principal(
                runner=run,
                principal=principal,
                secret_backend=secret_backend,
                dry_run=dry_run,
                key_path=resolved_env.get("REGISTA_KEY_PATH") or None,
            )
        )

    steps.append(
        bind_dossier_identity(
            principal=principal,
            env=resolved_env,
            dossier_user=dossier_user,
            installed=is_installed,
            dry_run=dry_run,
        )
    )

    frozen = tuple(steps)
    return IdentityResult(
        action=IdentityAction.ONBOARD,
        principal=principal,
        outcome=aggregate_outcome(frozen),
        steps=frozen,
    )


def run_user_offboarding(
    *,
    principal: str,
    reason: str = "offboarded",
    overlay_path: Path | None = None,
    keep_overlay: bool = False,
    dry_run: bool = False,
    runner: Runner | None = None,
    installed: Installed | None = None,
    env: Mapping[str, str] | None = None,
    dossier_user: str | None = None,
) -> IdentityResult:
    """Offboard one principal — the leaver process (onboarding doc §6).

    Revokes every active key, reports the secret-backend refs still to be
    removed, removes the dossier identity binding so it does not point at a
    revoked principal, and (unless ``keep_overlay``) removes the per-user
    overlay.
    """
    run = runner or _default_runner
    is_installed = installed or _default_installed
    path = overlay_path or user_suite_env_path()
    resolved_env: Mapping[str, str] = os.environ if env is None else env

    steps: list[IdentityStep] = []
    if not is_installed("regista"):
        steps.append(
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.FAILED,
                "regista not installed — cannot revoke the principal's keys",
            )
        )
    else:
        revoke_step, revoked = _revoke_keys(
            runner=run, principal=principal, reason=reason, dry_run=dry_run
        )
        steps.append(revoke_step)
        if revoke_step.outcome is not IdentityOutcome.FAILED:
            steps.append(
                _secret_backend_step(revoked, runner=run, dry_run=dry_run)
            )

    steps.append(
        unbind_dossier_identity(
            principal=principal,
            env=resolved_env,
            dossier_user=dossier_user,
            installed=is_installed,
            dry_run=dry_run,
        )
    )

    if keep_overlay:
        steps.append(
            IdentityStep(
                "user_overlay",
                IdentityOutcome.ALREADY_DONE,
                f"overlay at {path} left in place (--keep-overlay)",
            )
        )
    else:
        steps.append(remove_overlay(path, dry_run=dry_run))

    frozen = tuple(steps)
    return IdentityResult(
        action=IdentityAction.OFFBOARD,
        principal=principal,
        outcome=aggregate_outcome(frozen),
        steps=frozen,
    )


def format_result(result: IdentityResult) -> str:
    """Human-readable rendering (the non-``--json`` CLI path)."""
    lines = [f"{result.action.value} {result.principal}: {result.outcome.value}"]
    lines.extend(
        f"  {step.name:16s} {step.outcome.value:22s} {step.detail}"
        for step in result.steps
    )
    return "\n".join(lines)
