"""Skill-invocation smoke suite (Plan 018 WI-4 behavioral acceptance gate).

Runs each skill-documented agent-notes invocation against the locked
component version and asserts:

- clean JSON parses on stdout (no stripping needed),
- honest exit codes (no fail-open),
- grammar correctness (the documented invocation actually works).

Mutating verbs run against an ephemeral fixture project backed by the
interop Postgres. Grammar drift or reintroduced stream pollution fails
this suite — that is the point.

Requires: agent-notes + regista installed + INTEROP_DSN (or Docker).
Runs in the interop CI job. Skips cleanly locally when prerequisites
are absent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

from tests.conftest import _can_run, _generate_hmac_key

_SKIP_REASON = (
    "Skill smoke prerequisites not met — need agent-notes + regista + "
    "(Docker or INTEROP_DSN)."
)

_REQUIRE = os.environ.get("INTEROP_REQUIRE_FACES", "").strip().lower() in {
    "1", "true", "yes",
}


def _agent_notes_available() -> bool:
    return shutil.which("agent-notes") is not None


def _regista_available() -> bool:
    try:
        import regista  # noqa: F401

        return True
    except ImportError:
        return False


def _dsn_available() -> bool:
    return bool(
        os.environ.get("AGENT_NOTES_SMOKE_DSN") or os.environ.get("INTEROP_DSN")
    )


def _should_skip() -> bool:
    if not _agent_notes_available() or not _regista_available():
        return not _REQUIRE
    if not (_dsn_available() or _can_run()):
        return not _REQUIRE
    return False


def _run_cli(
    argv: tuple[str, ...],
    env: dict[str, str],
    *,
    timeout: float = 90.0,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, "PYTHONIOENCODING": "utf-8", **env}
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            env=merged,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=124,
            stdout="",
            stderr=f"skill-smoke: timed out after {timeout}s",
        )


def _assert_json_success(proc: subprocess.CompletedProcess[str], label: str) -> dict:
    """Assert exit 0 + pure JSON stdout (contract §1 + §2)."""
    if proc.returncode == 124:
        pytest.fail(f"{label}: timed out")
    assert proc.returncode == 0, (
        f"{label}: exit {proc.returncode}, expected 0; "
        f"stderr: {proc.stderr[-500:]!r}"
    )
    assert "Traceback" not in proc.stderr, (
        f"{label}: traceback on a success path; stderr: {proc.stderr[-500:]!r}"
    )
    stdout = proc.stdout.strip()
    assert stdout, f"{label}: empty stdout on a JSON success path"
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{label}: stdout is not a single JSON document ({exc}); "
            f"first 300 bytes: {stdout[:300]!r}"
        )


def _assert_json_honest_exit(
    proc: subprocess.CompletedProcess[str], label: str
) -> dict:
    """Assert pure-JSON stdout + an HONEST exit (0 iff the doc reports ok).

    For read-only health verbs whose exit legitimately depends on state: the
    contract is a well-formed document whose exit code agrees with its ``ok``
    field, not that the state is healthy.
    """
    if proc.returncode == 124:
        pytest.fail(f"{label}: timed out")
    assert "Traceback" not in proc.stderr, (
        f"{label}: traceback; stderr: {proc.stderr[-500:]!r}"
    )
    stdout = proc.stdout.strip()
    assert stdout, f"{label}: empty stdout on a JSON path"
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{label}: stdout is not a single JSON document ({exc}); "
            f"first 300 bytes: {stdout[:300]!r}"
        )
    ok = doc.get("ok")
    assert isinstance(ok, bool), f"{label}: missing/invalid 'ok' bool"
    assert (proc.returncode == 0) == ok, (
        f"{label}: dishonest exit — returncode {proc.returncode} vs ok={ok}"
    )
    return doc


def _assert_error(proc: subprocess.CompletedProcess[str], label: str) -> dict:
    """Assert nonzero exit + envelope on stdout (contract §2 + §3)."""
    if proc.returncode == 124:
        pytest.fail(f"{label}: timed out")
    assert proc.returncode != 0, (
        f"{label}: exit 0 on a documented error path (fail-open); "
        f"stdout: {proc.stdout[:200]!r}"
    )
    assert "Traceback" not in proc.stderr, (
        f"{label}: traceback on a documented error path; "
        f"stderr: {proc.stderr[-500:]!r}"
    )
    stdout = proc.stdout.strip()
    assert stdout, f"{label}: no envelope on stdout for a --json error path"
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"{label}: --json error stdout is not JSON: {stdout[:200]!r}"
        )
    assert doc.get("ok") is False, f"{label}: error envelope missing ok=false"
    assert "error" in doc, f"{label}: error envelope missing 'error' key"
    assert "code" in doc["error"], f"{label}: error envelope missing 'code'"
    return doc


# ---------------------------------------------------------------------------
# Fixture: ephemeral agent-notes project with regista schema
# ---------------------------------------------------------------------------

_EXISTING_PROJECT = "/projects/agent-notes"


@pytest.fixture(scope="module")
def smoke_project() -> Generator[dict[str, str], None, None]:
    """Provide an agent-notes project for smoke tests.

    agent-notes uses **two** Postgres DSNs by contract (agent-notes
    ``core/config.py``): ``AGENT_NOTES_DSN`` is the native domain store (its own
    ``public.projects``/``workspaces``/``memories``), and a *separate* regista
    DSN backs the optional regista face (per-project event schemas + regista's
    own ``public.projects`` catalog). The two ``public.projects`` tables are
    different shapes, so they MUST live in different databases — pointing both
    at one DB shadows regista's catalog (``schema_name`` column absent) and
    ephemeral project creation fails. See ``AGENT_NOTES_SMOKE_REGISTA_DSN``.

    In CI (fresh Postgres, both DSNs distinct): creates an ephemeral regista
    project in the regista store with full isolation. Locally: falls back to
    the existing registered project when a separate regista DSN is unavailable.
    """
    if _should_skip():
        pytest.skip(_SKIP_REASON)
    if not _agent_notes_available():
        if _REQUIRE:
            pytest.fail("INTEROP_REQUIRE_FACES=1 but agent-notes is not on PATH")
        pytest.skip(_SKIP_REASON)

    dsn = os.environ.get("AGENT_NOTES_SMOKE_DSN") or os.environ.get("INTEROP_DSN", "")
    if not dsn:
        if _REQUIRE:
            pytest.fail("AGENT_NOTES_SMOKE_DSN (or INTEROP_DSN) not set in CI")
        pytest.skip("AGENT_NOTES_SMOKE_DSN (or INTEROP_DSN) not set")

    # The regista face store — a DISTINCT database from the agent-notes domain
    # DSN (the two-DSN contract above). Falls back to INTEROP_DSN, which is a
    # pure regista store (no agent-notes schema applied to it).
    regista_dsn = (
        os.environ.get("AGENT_NOTES_SMOKE_REGISTA_DSN")
        or os.environ.get("INTEROP_DSN", "")
    )

    env = {"AGENT_NOTES_DSN": dsn}

    if _regista_available() and regista_dsn and regista_dsn != dsn:
        import regista
        from regista.testing import drop_project_schema

        slug = uuid.uuid4().hex[:8]
        project_name = f"skill_smoke_{slug}"
        project_dir = Path(f"/tmp/skill-smoke-{slug}")
        project_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--quiet", str(project_dir)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project_dir), "commit",
             "--allow-empty", "-m", "init", "--quiet"],
            check=True, capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "smoke", "GIT_AUTHOR_EMAIL": "s@t",
                 "GIT_COMMITTER_NAME": "smoke", "GIT_COMMITTER_EMAIL": "s@t"},
        )

        key_path = project_dir / "hmac_keys.json"
        _generate_hmac_key(key_path)

        try:
            # Create the regista project in the regista STORE (not the domain
            # DSN). project_name == regista_project_name("skill-smoke-<slug>")
            # so the face resolves the same schema from --path.
            sub = regista.Regista.create_project(regista_dsn, project_name, str(key_path))
            sub.register_workflow(regista.canonical_workflow_yaml())
            sub.close()
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            if _REQUIRE:
                pytest.fail(
                    "Ephemeral project creation failed (CI requires isolation)"
                )
        else:
            init_proc = _run_cli(
                ("agent-notes", "init", str(project_dir), "--no-hooks"),
                env,
            )
            if init_proc.returncode == 0:
                # Verbs run with BOTH DSNs + the writes gate on, so mutating
                # verbs route through the regista face into the store schema.
                # Pin the CANONICAL (highest-precedence) vars, not just the
                # legacy aliases — agent-notes config resolves REGISTA_DSN /
                # REGISTA_KEY_PATH ahead of the AGENT_NOTES_REGISTA_* aliases,
                # so a leaked production REGISTA_DSN in the operator's shell
                # would otherwise redirect these subprocess writes at prod.
                smoke_env = {
                    **env,
                    "REGISTA_DSN": regista_dsn,
                    "AGENT_NOTES_REGISTA_DSN": regista_dsn,
                    "AGENT_NOTES_REGISTA_WRITES": "1",
                    "REGISTA_KEY_PATH": str(key_path),
                    "AGENT_NOTES_REGISTA_HMAC_KEY_PATH": str(key_path),
                }
                yield {"path": str(project_dir), "dsn": dsn, **smoke_env}
                drop_project_schema(regista_dsn, project_name)
                shutil.rmtree(project_dir, ignore_errors=True)
                return
            drop_project_schema(regista_dsn, project_name)
            shutil.rmtree(project_dir, ignore_errors=True)
            if _REQUIRE:
                pytest.fail("agent-notes init failed in CI")
    elif _REQUIRE:
        pytest.fail(
            "CI requires a regista store DSN distinct from the agent-notes "
            "domain DSN (set AGENT_NOTES_SMOKE_REGISTA_DSN); got "
            f"regista_dsn={regista_dsn!r} domain_dsn={dsn!r}"
        )

    if not Path(_EXISTING_PROJECT).is_dir():
        pytest.skip("No fallback project available")

    yield {"path": _EXISTING_PROJECT, "dsn": dsn, **env}


# ---------------------------------------------------------------------------
# Read-only verbs (skills: start, find-breadcrumb, file-breadcrumb, add-memory)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_should_skip(), reason=_SKIP_REASON)
class TestReadOnlyVerbs:
    """Skill-documented read-only invocations must exit 0 with pure JSON."""

    def test_doctor_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(("agent-notes", "doctor", "--json"), smoke_project)
        # doctor is a read-only HEALTH verb: the contract is a well-formed
        # JSON document with an HONEST exit (0 iff ok), not "the project is
        # healthy". A fresh ephemeral smoke project legitimately reports
        # unhealthy for un-provisioned optionals (skills_installed /
        # harness_wired), so asserting exit 0 would test provisioning, not the
        # CLI contract (and would force a global install-harness side effect).
        _assert_json_honest_exit(proc, "doctor --json")

    def test_workspace_list_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(("agent-notes", "workspace", "list", "--json"), smoke_project)
        _assert_json_success(proc, "workspace list --json")

    def test_work_item_find_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "work-item", "find",
                "--path", smoke_project["path"],
                "--status", "open",
                "--limit", "10",
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "work-item find --json")

    def test_memory_list_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "memory", "list",
                "--path", smoke_project["path"],
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "memory list --json")

    def test_vocabulary_list_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "vocabulary", "list",
                "--workspace", "default",
                "--kind", "wi_kind",
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "vocabulary list --json")

    def test_search_all_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "search", "all", "smoke test",
                "--path", smoke_project["path"],
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "search all --json")

    def test_breadcrumb_reconcile_dry_run(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "breadcrumb", "reconcile",
                "--path", smoke_project["path"],
                "--lookback", "10",
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "breadcrumb reconcile --json")


# ---------------------------------------------------------------------------
# Mutating verbs (skills: file-breadcrumb, update-breadcrumb, reflect, add-memory)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_should_skip(), reason=_SKIP_REASON)
class TestMutatingVerbs:
    """Skill-documented mutating invocations against the fixture store."""

    def test_work_item_file_json(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "work-item", "file",
                "--path", smoke_project["path"],
                "--title", "Smoke test: WI-4 acceptance gate",
                "--body", "Filed by the skill-invocation smoke suite.",
                "--type", "todo",
                "--status", "open",
                "--severity", "low",
                "--json",
            ),
            smoke_project,
        )
        doc = _assert_json_success(proc, "work-item file --json")
        wi = doc.get("work_item", doc)
        assert "identifier" in wi, (
            f"work-item file: missing 'identifier' in response: {doc!r}"
        )

    def test_work_item_update_json(self, smoke_project: dict[str, str]) -> None:
        file_proc = _run_cli(
            (
                "agent-notes", "work-item", "file",
                "--path", smoke_project["path"],
                "--title", "Smoke test: update target",
                "--body", "Will be updated.",
                "--type", "todo",
                "--status", "open",
                "--severity", "low",
                "--json",
            ),
            smoke_project,
        )
        file_doc = _assert_json_success(file_proc, "work-item file (setup)")
        wi = file_doc.get("work_item", file_doc)
        identifier = wi["identifier"]

        proc = _run_cli(
            (
                "agent-notes", "work-item", "update", identifier,
                "--path", smoke_project["path"],
                "--status", "closed",
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "work-item update --json")

    def test_memory_add_json(self, smoke_project: dict[str, str]) -> None:
        name = f"smoke-test-{uuid.uuid4().hex[:8]}"
        proc = _run_cli(
            (
                "agent-notes", "memory", "add",
                "--path", smoke_project["path"],
                "--name", name,
                "--type", "reference",
                "--body", "Smoke test memory for WI-4 acceptance.",
                "--json",
            ),
            smoke_project,
        )
        _assert_json_success(proc, "memory add --json")


# ---------------------------------------------------------------------------
# Error paths (contract §2 + §3: nonzero exit + envelope)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_should_skip(), reason=_SKIP_REASON)
class TestErrorPaths:
    """Documented error fixtures must exit nonzero with the envelope."""

    def test_work_item_file_unknown_type(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            (
                "agent-notes", "work-item", "file",
                "--path", smoke_project["path"],
                "--title", "Smoke test: bad type",
                "--body", "Should fail.",
                "--type", "nonexistent_kind_xyz",
                "--status", "open",
                "--severity", "low",
                "--json",
            ),
            smoke_project,
        )
        _assert_error(proc, "work-item file (unknown type)")

    def test_work_item_update_unknown_identifier(
        self, smoke_project: dict[str, str]
    ) -> None:
        bogus = f"WI-{uuid.uuid4().int % 900000 + 100000}"
        proc = _run_cli(
            (
                "agent-notes", "work-item", "update", bogus,
                "--path", smoke_project["path"],
                "--status", "closed",
                "--json",
            ),
            smoke_project,
        )
        _assert_error(proc, "work-item update (unknown identifier)")

    def test_work_item_get_unknown_identifier(
        self, smoke_project: dict[str, str]
    ) -> None:
        bogus = f"WI-{uuid.uuid4().int % 900000 + 100000}"
        proc = _run_cli(
            (
                "agent-notes", "work-item", "get", bogus,
                "--path", smoke_project["path"],
                "--json",
            ),
            smoke_project,
        )
        _assert_error(proc, "work-item get (unknown identifier)")


# ---------------------------------------------------------------------------
# Usage errors (contract §2: exit 2)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_should_skip(), reason=_SKIP_REASON)
class TestUsageErrors:
    """Malformed invocations must exit 2 without traceback."""

    def test_unknown_verb(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(("agent-notes", "no-such-verb"), smoke_project)
        assert proc.returncode == 2, (
            f"unknown verb: exit {proc.returncode}, expected 2"
        )
        assert "Traceback" not in proc.stderr, (
            "traceback on a usage error"
        )

    def test_missing_required_flag(self, smoke_project: dict[str, str]) -> None:
        proc = _run_cli(
            ("agent-notes", "work-item", "file", "--json"),
            smoke_project,
        )
        assert proc.returncode == 2, (
            f"missing required flag: exit {proc.returncode}, expected 2"
        )
        assert "Traceback" not in proc.stderr, (
            "traceback on a usage error"
        )
