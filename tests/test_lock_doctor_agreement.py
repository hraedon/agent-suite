"""Regression: ``agent-suite lock --check`` and ``agent-suite doctor`` agree.

Sol's review finding #1: the umbrella doctor reported a green lock
(``lock.matches: True``) while ``lock --check`` detected revision drift,
because ``_check_lock_drift`` never passed ``component_revisions`` to
``check_drift`` (so revisions were invisible to the doctor) and lock drift did
not affect ``suite_ok`` (so a red lock was smoothed into a green suite).

These tests pin the contract: the two commands must agree on whether the lock
is healthy. When ``lock --check`` would exit non-zero, ``doctor`` must report
``suite_ok: False`` — a red lock must produce a red suite. All component
doctors and the revision probe are stubbed so the test is hermetic (no live
infra, no real git checkouts).
"""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

from agent_suite.components import COMPONENTS
from agent_suite.config import MemoryProviderConfig
from agent_suite.doctor import aggregate
from agent_suite.lock import (
    ComponentPin,
    DriftKind,
    SuiteLock,
    check_drift,
    write_lock_file,
)

# Two distinct full git SHAs (sha-1 length). _SHA_A is what the lock pins;
# _SHA_B is what the revision probe "sees" in the local checkout.
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=0, stdout=stdout, stderr="")


def _ok_json(component: str, version: str = "1.0.0") -> str:
    """A healthy component doctor --json payload (matches the contract shape)."""
    return json.dumps(
        {
            "component": component,
            "version": version,
            "ok": True,
            "regista": {"reachable": True, "project": "x", "chain_ok": True},
            "checks": [{"name": "regista", "status": "ok", "detail": ""}],
        }
    )


def _versions(version: str = "1.0.0") -> dict[str, str | None]:
    return {c.ident: version for c in COMPONENTS}


class StubRunner:
    """Returns canned ``doctor --json`` output per component CLI name."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return _completed(stdout=self._outputs.get(cmd[0], ""))


def _lock_with_revisions(revision: str | None) -> SuiteLock:
    """Pin every component at version 1.0.0 with the given revision.

    ``regista_quad`` is None so the fixture isolates *revision* drift — the
    regista quad is absent on both sides (no regista installed), so no quad
    drift is reported. Versions match exactly, so the only possible drift is
    the revision mismatch.
    """
    return SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={
            c.ident: ComponentPin(repo=c.repo, version="1.0.0", revision=revision)
            for c in COMPONENTS
        },
    )


def _doctor_report(
    lock_path: Path,
    *,
    revision_probe: object,
) -> object:
    """Run the doctor umbrella against the fixture with all optional checks off.

    ``version_installed=lambda _: False`` keeps regista absent (current_quad
    is None, matching the lock's None quad) so the test isolates revision
    drift. ``memory_provider_config`` is pinned to native so no hindsight
    endpoint env var can leak in and affect ``suite_ok``.
    """
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident, version="1.0.0") for c in COMPONENTS}
    return aggregate(
        installed=lambda _cli: True,
        runner=StubRunner(outputs),
        components=COMPONENTS,
        lock_path=lock_path,
        version_installed=lambda _: False,
        revision_probe=revision_probe,  # type: ignore[arg-type]
        memory_provider_config=MemoryProviderConfig(engine="native"),
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=False,
    )


# ---------------------------------------------------------------------------
# The core regression: revision drift must red both commands
# ---------------------------------------------------------------------------


def test_revision_drift_reds_both_lock_check_and_doctor(tmp_path: Path) -> None:
    """A drifted revision makes both ``lock --check`` and ``doctor`` fail.

    This is the exact false-green scenario: every component is healthy and its
    version matches the lock, but the locked revision differs from the probed
    SHA. Before the fix, ``doctor`` reported ``lock.matches: True`` (revisions
    never probed) and ``suite_ok: True`` (lock drift ignored) — a green suite
    over a red lock. After the fix, both commands report failure.
    """
    lock_path = tmp_path / "SUITE.lock"
    locked = _lock_with_revisions(_SHA_A)
    write_lock_file(locked, lock_path)

    versions = _versions("1.0.0")
    current_revisions = {c.ident: _SHA_B for c in COMPONENTS}

    # --- the `lock --check` path: check_drift with revisions (what the CLI does) ---
    lock_drift = check_drift(
        locked,
        current_quad=None,
        component_versions=versions,
        component_revisions=current_revisions,
    )
    assert lock_drift.matches is False
    rev_drifts = [d for d in lock_drift.drift if d.kind is DriftKind.REVISION_MISMATCH]
    assert len(rev_drifts) == len(COMPONENTS)
    # lock --check exits non-zero when matches is False (cli.py: `0 if matches else 1`)
    assert lock_drift.matches is not True

    # --- the `doctor` path: aggregate with the same revisions injected ---
    report = _doctor_report(lock_path, revision_probe=lambda: current_revisions)

    # The doctor must see the SAME drift the lock command sees — not a
    # smoothed "matches: True". The drift entries are identical because both
    # paths feed the same inputs to check_drift.
    assert report.lock.matches is False  # type: ignore[union-attr]
    assert report.lock.drift == lock_drift.drift  # type: ignore[union-attr]

    # And a red lock must produce a red suite — the core contract.
    assert report.suite_ok is False  # type: ignore[union-attr]


def test_matching_revisions_green_both_lock_check_and_doctor(tmp_path: Path) -> None:
    """When revisions match, both ``lock --check`` and ``doctor`` report healthy.

    The inverse of the regression: no drift, all components healthy -> both
    commands agree the lock is healthy and the suite is OK.
    """
    lock_path = tmp_path / "SUITE.lock"
    locked = _lock_with_revisions(_SHA_A)
    write_lock_file(locked, lock_path)

    versions = _versions("1.0.0")
    current_revisions = {c.ident: _SHA_A for c in COMPONENTS}

    lock_drift = check_drift(
        locked,
        current_quad=None,
        component_versions=versions,
        component_revisions=current_revisions,
    )
    assert lock_drift.matches is True
    assert lock_drift.drift == []

    report = _doctor_report(lock_path, revision_probe=lambda: current_revisions)
    assert report.lock.matches is True  # type: ignore[union-attr]
    assert report.lock.drift == []  # type: ignore[union-attr]
    assert report.suite_ok is True  # type: ignore[union-attr]


def test_no_lock_file_is_informational_not_a_suite_failure(tmp_path: Path) -> None:
    """No lock file -> ``matches=None``, and the suite is NOT failed by the lock.

    The contract distinguishes "no baseline" (None, informational — does not
    fail ``suite_ok``) from "drift" (False, fails ``suite_ok``). A suite with
    no lock file but all components healthy is OK; the lock section honestly
    reports "no SUITE.lock."
    """
    report = _doctor_report(
        tmp_path / "nonexistent.lock", revision_probe=lambda: {}
    )
    assert report.lock.matches is None  # type: ignore[union-attr]
    assert "no SUITE.lock" in report.lock.note  # type: ignore[union-attr]
    # No lock drift (matches is None, not False) -> suite_ok stays True.
    assert report.suite_ok is True  # type: ignore[union-attr]


def test_doctor_default_revision_probe_is_the_real_lock_probe() -> None:
    """``aggregate`` resolves a None ``revision_probe`` to the real lock probe.

    This is what makes the CLI ``doctor`` command probe revisions the same way
    ``lock --check`` does, with no explicit wiring at the call site. The
    default must be :func:`agent_suite.lock.read_component_revisions` (not a
    no-op) so the two commands agree against real checkouts.
    """
    import agent_suite.doctor as doctor_mod
    import agent_suite.lock as lock_mod

    # aggregate's param defaults to None (resolved inside to the real probe).
    agg_sig = inspect.signature(doctor_mod.aggregate)
    assert agg_sig.parameters["revision_probe"].default is None

    # _check_lock_drift's param defaults directly to the real probe.
    cld_sig = inspect.signature(doctor_mod._check_lock_drift)
    assert cld_sig.parameters["revision_probe"].default is lock_mod.read_component_revisions


def test_lock_check_memory_provider_drift_uses_current_provider() -> None:
    """WI-003 regression: lock --check must not false-positive provider drift.

    When the lock pins a memory-provider extension (e.g. hindsight) and the
    operator's current engine matches, lock --check must NOT report
    provider_extension drift. Prior to this fix, lock --check passed None
    for current_provider_extension even when the engine was configured,
    causing every check to report 'pinned -> absent'.
    """
    from agent_suite.lock import (
        ComponentPin,
        ProviderExtension,
        SuiteLock,
        check_drift,
        RegistaVersionQuad,
    )

    quad = RegistaVersionQuad(
        library_version="0.5.1",
        schema_version=43,
        canonical_workflow_version="2",
        envelope_version=5,
    )
    pe = ProviderExtension(
        provider_name="hindsight",
        adapter_version="0.8.4",
        protocol_version="1.0",
        deployment_mode="remote",
        support_level="supported",
        config_digest=None,
    )
    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=quad,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.5.1")},
        provider_extension=pe,
    )

    # Case 1: current_provider_extension is None (the bug) — false drift.
    result_buggy = check_drift(
        lock,
        current_quad=quad,
        component_versions={"regista": "0.5.1"},
        current_provider_extension=None,
    )
    assert result_buggy.matches is False
    assert any(
        d.kind.value == "provider_drift" and d.field == "provider_extension"
        for d in result_buggy.drift
    ), "absent current provider must produce named provider_drift"

    # Case 2: current_provider_extension matches — no drift (the fix).
    result_fixed = check_drift(
        lock,
        current_quad=quad,
        component_versions={"regista": "0.5.1"},
        current_provider_extension=pe,
    )
    assert result_fixed.matches is True, (
        f"matching provider must not drift; got: {[d.to_dict() for d in result_fixed.drift]}"
    )
