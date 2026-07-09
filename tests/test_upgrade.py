"""Unit tests for the upgrade module — advancement check, apply, rollback, interop gate.

All tests use stubbed runners and installed checks — no live infra (AGENTS.md:
"Ordering/idempotency unit-tested with stubbed component CLIs (no live infra
in CI)").
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping


from agent_suite.components import COMPONENTS
from agent_suite.lock import ComponentPin, RegistaVersionQuad, SuiteLock, serialize_lock
from agent_suite.upgrade import (
    AdvancementReport,
    AdvancementStatus,
    ApplyStatus,
    ComponentAdvancement,
    RollbackResult,
    RollbackStatus,
    UpgradeResult,
    check_advancements,
    format_advancement_text,
    format_rollback_text,
    format_upgrade_text,
    run_rollback,
    run_upgrade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


_QUAD = RegistaVersionQuad(
    library_version="0.4.0",
    schema_version=38,
    canonical_workflow_version="2",
    envelope_version=4,
)


def _lock(versions: dict[str, str], quad: RegistaVersionQuad | None = None) -> SuiteLock:
    return SuiteLock(
        release="1.0.0",
        regista_quad=quad or _QUAD,
        components={
            ident: ComponentPin(repo=f"hraedon/{ident}", version=ver)
            for ident, ver in versions.items()
        },
    )


class StubRunner:
    """Routes stubbed output by matching command prefixes."""

    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                return out
        return _completed(stdout="", returncode=1, stderr="unknown command")


def _pip_would_install(package: str, version: str) -> str:
    return f"Collecting {package}\n  Using cached {package}-{version}-py3-none-any.whl\nWould install {package}-{version}\n"


def _pip_already_satisfied(package: str, version: str) -> str:
    return f"Requirement already satisfied: {package}=={version}\n"


# ---------------------------------------------------------------------------
# check_advancements (--check, read-only)
# ---------------------------------------------------------------------------


def test_check_reports_advancement_available() -> None:
    runner = StubRunner({
        ("pip",): _completed(
            stdout=_pip_would_install("regista", "0.5.0"),
            stderr="",
        ),
    })
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert len(report.advancements) == 1
    a = report.advancements[0]
    assert a.status is AdvancementStatus.ADVANCEMENT_AVAILABLE
    assert a.target_version == "0.5.0"


def test_check_reports_up_to_date() -> None:
    runner = StubRunner({
        ("pip",): _completed(
            stdout="",
            stderr=_pip_already_satisfied("regista", "0.4.0"),
        ),
    })
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.UP_TO_DATE


def test_check_reports_not_installed() -> None:
    report = check_advancements(
        component="regista",
        runner=StubRunner({}),
        installed=lambda _: False,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.NOT_INSTALLED


def test_check_reports_unreachable_on_pip_missing() -> None:
    def raise_fnf(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("pip")
    report = check_advancements(
        component="regista",
        runner=raise_fnf,  # type: ignore[arg-type]
        installed=lambda _: True,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.UNREACHABLE


def test_check_unknown_component_returns_empty() -> None:
    report = check_advancements(
        component="nonexistent",
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert report.advancements == []
    assert "unknown component" in report.note


def test_check_all_components() -> None:
    runner = StubRunner({
        ("pip",): _completed(
            stdout=_pip_would_install("regista", "0.5.0"),
            stderr="",
        ),
    })
    report = check_advancements(
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert len(report.advancements) == len(COMPONENTS)


# ---------------------------------------------------------------------------
# run_upgrade --check
# ---------------------------------------------------------------------------


def test_upgrade_check_only_is_read_only() -> None:
    runner = StubRunner({
        ("pip",): _completed(stdout="Requirement already satisfied: regista\n"),
    })
    result = run_upgrade(
        check_only=True,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is True
    assert result.check_only is True
    # check_only discovers advancements (read-only pip calls) but does not write/upgrade
    assert all(s.status is not ApplyStatus.APPLIED for s in result.apply_steps)
    assert len(result.apply_steps) == 0  # no apply steps in check-only mode


# ---------------------------------------------------------------------------
# run_upgrade --dry-run
# ---------------------------------------------------------------------------


def test_upgrade_dry_run_does_not_act(tmp_path: Path) -> None:
    lock = _lock({"regista": "0.4.0"})
    lock_text = serialize_lock(lock)
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(lock_text)

    result = run_upgrade(
        dry_run=True,
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
        lock_path=lock_path,
    )
    assert result.ok is True
    assert result.dry_run is True
    assert all(s.status is ApplyStatus.SKIPPED for s in result.apply_steps)


# ---------------------------------------------------------------------------
# run_upgrade — no lock
# ---------------------------------------------------------------------------


def test_upgrade_without_lock_fails(tmp_path: Path) -> None:
    result = run_upgrade(
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
        lock_path=tmp_path / "nonexistent.lock",
    )
    assert result.ok is False
    assert "no SUITE.lock" in result.detail


# ---------------------------------------------------------------------------
# run_upgrade — unknown component
# ---------------------------------------------------------------------------


def test_upgrade_unknown_component_fails() -> None:
    result = run_upgrade(
        component="nonexistent",
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert "unknown component" in result.detail


# ---------------------------------------------------------------------------
# run_rollback — migration boundary refusal
# ---------------------------------------------------------------------------


def test_rollback_refuses_schema_migration_boundary(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.3.0"}, quad=RegistaVersionQuad(
        library_version="0.3.0", schema_version=37,
        canonical_workflow_version="2", envelope_version=4,
    ))
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
        ("regista", "version"): _completed(stdout=json.dumps({
            "library_version": "0.4.0", "schema_version": 38,
            "canonical_workflow_version": "2", "envelope_version": 4,
        })),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.REFUSED_MIGRATION_BOUNDARY
    assert "schema migration boundary" in result.detail
    assert result.current_schema_version == 38
    assert result.target_schema_version == 37


def test_rollback_succeeds_when_schema_matches(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.4.0"}, quad=_QUAD)
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
        ("regista", "version"): _completed(stdout=json.dumps({
            "library_version": "0.4.0", "schema_version": 38,
            "canonical_workflow_version": "2", "envelope_version": 4,
        })),
        ("pipx", "install"): _completed(stdout="installed"),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is True
    assert result.status is RollbackStatus.APPLIED
    assert lock_path.exists()


def test_rollback_fails_when_git_ref_missing(tmp_path: Path) -> None:
    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(returncode=1, stderr="bad revision"),
    })

    result = run_rollback(
        to_ref="bad-ref",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.FAILED
    assert "no SUITE.lock" in result.detail


def test_rollback_refuses_when_current_schema_unknown(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.4.0"}, quad=_QUAD)
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: False,  # regista not installed
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.FAILED
    assert "cannot determine current schema" in result.detail


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_advancement_text() -> None:
    report = AdvancementReport(
        advancements=[
            ComponentAdvancement(
                component="regista",
                current_version="0.4.0",
                target_version="0.5.0",
                status=AdvancementStatus.ADVANCEMENT_AVAILABLE,
                detail="0.4.0 -> 0.5.0",
            ),
        ],
        note="1 advancement(s) available: regista",
    )
    text = format_advancement_text(report)
    assert "regista" in text
    assert "0.5.0" in text


def test_format_upgrade_text_dry_run() -> None:
    result = UpgradeResult(ok=True, dry_run=True, check_only=False, component_filter=None)
    text = format_upgrade_text(result)
    assert "dry-run" in text
    assert "OK" in text


def test_format_rollback_text_refused() -> None:
    result = RollbackResult(
        ok=False,
        status=RollbackStatus.REFUSED_MIGRATION_BOUNDARY,
        target_ref="HEAD~1",
        current_schema_version=38,
        target_schema_version=37,
        detail="refused: schema migration boundary",
    )
    text = format_rollback_text(result)
    assert "refused" in text
    assert "38" in text
    assert "37" in text
