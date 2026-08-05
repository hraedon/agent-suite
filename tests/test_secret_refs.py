"""Step 0 must resolve the refs this host has, not list providers (WI-041/WI-039).

The qualification host's only ``vault:`` ref was repointed at a Vault path its
AppRole is denied — proved 403 — and ``bootstrap`` printed:

    probe_secrets      done           secret backend reachable
    ...
    bootstrap: OK

`docs/secrets-vault.md` §8 promised the opposite. These tests pin the three
traps that estate hit, and pin that a doc can no longer print a ``vault:`` ref
shape the resolver rejects.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from agent_suite.bootstrap import StepKind, StepStatus, run_bootstrap
from agent_suite.secret_refs import (
    BACKEND_REF_LITERAL_RE,
    config_problems,
    discover_refs,
    probe_ref_argv,
    ref_static_problem,
    scheme_of,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# Trap 2: the field is the last path segment, and '#field' silently mis-parses
# ---------------------------------------------------------------------------


def test_hash_field_form_is_rejected_statically() -> None:
    """``#field`` never worked, and against a real mount it reads a *neighbour*.

    ``vault:kv/a/b/regista#hmac_key`` parses to mount ``kv``, path ``a/b``,
    field ``regista#hmac_key`` — a different secret from the one the operator
    named. On a permissive policy it succeeds at reading the wrong thing, so a
    resolve-only check would not catch it. This is why the shape is also checked
    statically.
    """
    problem = ref_static_problem("vault:kv/agent-suite/hosts/qual-linux/regista#hmac_key")
    assert problem is not None
    assert "LAST PATH SEGMENT" in problem
    assert "neighbouring" in problem


def test_three_segment_vault_ref_is_rejected() -> None:
    """The exact line suite.env.example and three install docs used to print."""
    problem = ref_static_problem("vault:secret/agent-suite/regista#signing_key")
    assert problem is not None


def test_correct_vault_shape_has_no_static_problem() -> None:
    assert (
        ref_static_problem("vault:kv/agent-suite/qual/hosts/qual-linux/regista/hmac_key")
        is None
    )


def test_scheme_names_match_the_resolver_vocabulary() -> None:
    assert scheme_of("vault:kv/a/b/c") == "vault"
    assert scheme_of("file:/etc/agent-suite/keys.json") == "file"
    assert scheme_of("/etc/agent-suite/keys.json") == "file"
    # 'akv:' and 'wincred:' are doc inventions; the resolver knows azure/windows.
    assert scheme_of("akv:vault-name/secret") == "literal"
    assert ref_static_problem("akv:vault-name/secret") is not None
    assert ref_static_problem("wincred:agent-suite/regista/signing-key") is not None
    # Correct scheme names are recognised.
    assert scheme_of("azure:regista-dsn-password") == "azure"
    assert scheme_of("windows:AQAAANCMnd8B") == "windows"


def test_azure_ref_shape_is_validated() -> None:
    """``azure:`` takes a bare KV secret name, not an embedded vault DNS."""
    # The bare secret-name shape works.
    assert ref_static_problem("azure:regista-dsn-password") is None
    # Embedding the vault DNS (the old akv: shape, corrected to the right
    # scheme) is still the wrong *shape* and must be caught.
    bad_azure = "azure:suite-secrets.vault.azure.net/regista-dsn-password"
    assert ref_static_problem(bad_azure) is not None


def test_windows_ref_shape_is_validated() -> None:
    """``windows:`` takes the base64 DPAPI blob, not a credential target."""
    # A base64 blob (the ref IS the blob) works.
    assert ref_static_problem("windows:AQAAANCMnd8B") is None
    # A credential-target name (the old wincred: shape, corrected to the right
    # scheme) is still the wrong *shape* and must be caught.
    bad_windows = "windows:agent-suite/regista/signing-key"
    assert ref_static_problem(bad_windows) is not None


# ---------------------------------------------------------------------------
# Discovery: what refs does this host actually have?
# ---------------------------------------------------------------------------


def test_discovers_env_refs_and_key_file_refs(tmp_path: Path) -> None:
    key_file = tmp_path / "keys.json"
    key_file.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "qual-linux-2026-07",
                        "secret_ref": "vault:kv/agent-suite/qual/hosts/qual-linux/regista/hmac_key",
                        "encoding": "base64",
                    },
                    {"key_id": "inline", "secret": "not-a-ref"},
                ]
            }
        )
    )
    refs = discover_refs(
        {
            "REGISTA_KEY_PATH": str(key_file),
            "CAIRN_CONTENT_KEY_REF": "vault:kv/agent-suite/qual/hosts/qual-linux/cairn/content_key",
            "REGISTA_DSN": "postgresql://user:pw@localhost/regista",
            "DOSSIER_USERS_PATH": "/etc/agent-suite/users.json",
            "PATH": "/usr/bin",
        }
    )
    by_ref = {r.ref: r for r in refs}
    assert set(by_ref) == {
        "vault:kv/agent-suite/qual/hosts/qual-linux/regista/hmac_key",
        "vault:kv/agent-suite/qual/hosts/qual-linux/cairn/content_key",
    }
    # The owning CLI is named, because hvac must be importable in *its* venv.
    assert by_ref[
        "vault:kv/agent-suite/qual/hosts/qual-linux/cairn/content_key"
    ].owner_cli == "cairn"
    assert "keys.json" in by_ref[
        "vault:kv/agent-suite/qual/hosts/qual-linux/regista/hmac_key"
    ].source


def test_key_path_as_a_ref_is_reported_as_a_configuration_error() -> None:
    """Trap: ``REGISTA_KEY_PATH`` is a path to a keys.json FILE, not a ref."""
    problems = config_problems(
        {"REGISTA_KEY_PATH": "vault:secret/agent-suite/regista/signing_key"}
    )
    assert problems
    assert "keys.json" in problems[0]


def test_dsn_password_variable_is_reported_as_ignored() -> None:
    problems = config_problems({"REGISTA_DSN_PASSWORD": "vault:kv/a/b/dsn_password"})
    assert problems
    assert "silently" in problems[0]


def test_probe_never_asks_for_the_secret_on_stdout_in_a_readable_way() -> None:
    """The probe command is fixed here so nobody 'improves' it into a leak.

    ``regista secrets --ref`` prints the resolved secret on stdout; the probe
    reads only the exit code, and the failure envelope.
    """
    assert probe_ref_argv("vault:kv/a/b/c") == (
        "regista",
        "--json",
        "secrets",
        "--ref",
        "vault:kv/a/b/c",
    )


# ---------------------------------------------------------------------------
# The step itself
# ---------------------------------------------------------------------------


def _bootstrap(env: dict[str, str], runner) -> object:
    return run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env=env,
        installed=lambda _cli: True,
    )


def _step(result, kind: StepKind):
    return next(s for s in result.steps if s.step is kind)


def test_unresolvable_ref_aborts_the_bootstrap(tmp_path: Path) -> None:
    """The exact qualification scenario: one configured ref, provably 403."""
    denied = "vault:kv/agent-suite/qual/hosts/other-host/regista/hmac_key"

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ("regista", "--json", "secrets", "--ref"):
            return _completed(
                returncode=1,
                stdout=json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "KEY_LOAD_ERROR",
                            "message": "vault: permission denied",
                            "detail": None,
                            "retryable": False,
                            "partial": None,
                        },
                    }
                ),
            )
        raise AssertionError(f"step 0 must abort before {cmd}")

    result = _bootstrap({"CAIRN_CONTENT_KEY_REF": denied}, runner)
    assert result.ok is False
    probe = _step(result, StepKind.PROBE_SECRETS)
    assert probe.status is StepStatus.FAILED
    # The failing ref is named, which is what the doc promised.
    assert denied in probe.detail
    assert "permission denied" in probe.detail
    # And nothing was provisioned against an unresolvable secret.
    assert _step(result, StepKind.PROVISION).status is StepStatus.SKIPPED


def test_provider_list_alone_no_longer_greens_the_step() -> None:
    """A registered provider is not a resolved reference.

    The old step ran ``regista secrets --list-providers`` and called that
    "secret backend reachable". Here the provider list succeeds and the resolve
    fails; the step must fail.
    """
    calls: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:3] == ("regista", "secrets", "--list-providers"):
            return _completed(stdout="Available providers:\n  file\n  vault\n")
        if cmd[:4] == ("regista", "--json", "secrets", "--ref"):
            return _completed(returncode=1, stderr="hvac.exceptions.Forbidden")
        raise AssertionError(f"unexpected call {cmd}")

    result = _bootstrap(
        {"REGISTA_HMAC_KEY_REF": "vault:kv/agent-suite/hosts/h/regista/hmac_key"},
        runner,
    )
    assert result.ok is False
    assert _step(result, StepKind.PROBE_SECRETS).status is StepStatus.FAILED


def test_resolvable_refs_pass_and_the_step_says_what_it_verified() -> None:
    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ("regista", "--json", "secrets", "--ref"):
            # stdout would be the secret itself; the step must not echo it.
            return _completed(stdout="s3cret-key-material")
        if cmd[:2] == ("regista", "doctor"):
            return _completed(stdout='{"reachable": true, "ok": true}')
        if cmd[:2] == ("regista", "provision"):
            return _completed(
                stdout=json.dumps([{
                    "project": "qual_linux",
                    "schema_created": True,
                    "migrations_applied": [],
                    "service_role_created": True,
                    "error": None,
                }])
            )
        if cmd[:2] == ("regista", "provision-principal"):
            return _completed(
                stdout=json.dumps({
                    "principal_id": "suite-service",
                    "project": "qual_linux",
                    "key_id": "pk_1",
                    "already_existed": False,
                    "public_key_registered": True,
                    "error": None,
                })
            )
        if cmd[:2] == ("agent-notes", "doctor"):
            return _completed(
                stdout=json.dumps({
                    "ok": True,
                    "checks": [
                        {"name": "schema_up_to_date", "status": "ok", "detail": "current"}
                    ],
                })
            )
        return _completed(
            stdout=json.dumps({
                "tool": cmd[0], "harness": cmd[2] if len(cmd) > 2 else "all",
                "status": "installed", "actions": [], "no_op": False,
            })
        )

    result = _bootstrap(
        {"CAIRN_CONTENT_KEY_REF": "vault:kv/agent-suite/hosts/h/cairn/content_key"},
        runner,
    )
    probe = _step(result, StepKind.PROBE_SECRETS)
    assert probe.status is StepStatus.DONE
    assert "resolved 1 configured secret ref" in probe.detail
    assert "s3cret" not in probe.detail
    # It says plainly what it did *not* verify: cairn's own environment.
    assert "cairn" in probe.detail


def test_no_refs_configured_does_not_claim_to_have_verified_anything() -> None:
    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ("regista", "secrets", "--list-providers"):
            return _completed(stdout="Available providers:\n  file\n")
        raise AssertionError(f"unexpected call {cmd}")

    from agent_suite.bootstrap import _step_probe_secrets

    step = _step_probe_secrets(
        runner=runner, installed=lambda _c: True, dry_run=False, env={}
    )
    assert step.status is StepStatus.DONE
    assert "nothing to resolve" in step.detail


# ---------------------------------------------------------------------------
# WI-039: no document may print a vault: ref the resolver cannot parse
# ---------------------------------------------------------------------------


def _documented_backend_refs() -> list[tuple[Path, str]]:
    """Every backend-ref literal the committed docs and examples print.

    Matches any of the resolver's known schemes (vault/azure/windows/file/env)
    followed by a non-empty body. Prose that merely lists scheme names
    (``vault:/azure:/windows:``) is filtered out because its body contains a
    second ``:``.

    Known residual (WI-071 L6, by design): the match truncates at ``<``
    placeholder markers, so ``azure:principal-<principal_id>-key`` validates
    only its ``azure:principal-`` prefix and a ref written entirely as a
    placeholder (``windows:<base64-dpapi-blob>``) is invisible to this gate.
    Docs that print refs only in placeholder form are therefore not proven
    parseable here — the concrete-literal cases below carry that weight.
    """
    found: list[tuple[Path, str]] = []
    candidates = sorted((REPO_ROOT / "docs").rglob("*.md"))
    candidates.append(REPO_ROOT / "suite.env.example")
    for path in candidates:
        if not path.is_file():
            continue
        for match in BACKEND_REF_LITERAL_RE.finditer(path.read_text(encoding="utf-8")):
            literal = match.group(0).rstrip(".,;:)`\"'")
            _scheme, _sep, body = literal.partition(":")
            # `<scheme>:` on its own, or in a list of scheme names
            # ("vault:/azure:/windows:"), is prose about the scheme rather than
            # a reference. A reference has a path and no second scheme in it.
            if not body or ":" in body:
                continue
            found.append((path.relative_to(REPO_ROOT), literal))
    return found


def test_every_documented_backend_ref_parses() -> None:
    """A pure-parse assertion — no backend needed, and none of it is optional.

    Every documented backend-ref literal must both (a) use a scheme the
    resolver knows and (b) have a shape the resolver accepts. This is what
    catches a doc that prints ``akv:``/``wincred:`` (unknown scheme) or the
    old embedded-DNS / credential-target shapes even after the scheme name is
    corrected (WI-039/WI-069).
    """
    literals = _documented_backend_refs()
    assert literals, "the docs stopped mentioning backend refs — update this test"
    broken = [
        (str(path), literal, ref_static_problem(literal))
        for path, literal in literals
        if ref_static_problem(literal) is not None
    ]
    assert broken == []


@pytest.mark.parametrize(
    "literal",
    [
        "vault:secret/agent-suite/regista#signing_key",
        "vault:kv/a/b#field",
        "akv:suite-secrets.vault.azure.net/regista-dsn-password",
        "wincred:agent-suite/regista/signing-key",
        "azure:suite-secrets.vault.azure.net/regista-dsn-password",
        "windows:agent-suite/regista/signing-key",
    ],
)
def test_the_docs_test_would_have_caught_the_shipped_shape(literal: str) -> None:
    """Proof the guard has teeth: the shapes that shipped are rejected."""
    assert ref_static_problem(literal) is not None
    assert re.fullmatch(BACKEND_REF_LITERAL_RE, literal)
