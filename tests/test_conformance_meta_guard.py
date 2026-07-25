"""WI-026 meta-guard: prove the conformance gate *runs*, not *skips*.

The silent-skip bug (2026-07-24) bit three components: their
``test_cli_conformance.py`` did ``pytest.importorskip("agent_suite.conformance")``
against a module that was never installed, so every case skipped, CI stayed
green, and zero contract was enforced. A skipped gate is indistinguishable from
a passing one in a green build — the canonical "fails open" hazard.

``assert_cases_declared`` (dogfooded in ``test_cli_conformance.py``) catches the
"module loaded but a dimension is empty" half of the class. This file catches
the other half — "the whole module skipped" — by running the conformance module
as a subprocess and asserting at least one case *passed* (not all-skipped).

The guard is factored into a pure function (``require_gate_ran``) so a deny-case
can prove it rejects an all-skip summary — not a tautology (process-calibration
§5). An end-to-end falsifier builds a tiny module that importorskip's a bogus
name and confirms the guard flags it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from agent_suite.conformance import ConformanceGateError

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_TEST = REPO_ROOT / "tests" / "test_cli_conformance.py"

_COUNT_RE = {
    "passed": re.compile(r"(\d+)\s+passed"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
    "failed": re.compile(r"(\d+)\s+failed"),
    "error": re.compile(r"(\d+)\s+error"),
}


def _summary_counts(output: str) -> dict[str, int]:
    """Parse the *last* occurrence of each pytest summary count from ``output``.

    pytest prints one summary line (e.g. "10 passed in 1.24s" or
    "3 passed, 2 skipped in 0.5s"); the last match for each key is the
    authoritative total. Absent keys are 0.
    """
    counts: dict[str, int] = {}
    for key, pattern in _COUNT_RE.items():
        matches = pattern.findall(output)
        counts[key] = int(matches[-1]) if matches else 0
    return counts


def require_gate_ran(output: str, *, minimum_passed: int = 1) -> dict[str, int]:
    """Meta-guard: assert the conformance gate ran at least ``minimum_passed`` cases.

    Raises ``ConformanceGateError`` when no case passed — the signature of an
    importorskip skip (or a collection failure). Returns the parsed counts so a
    caller can record them.
    """
    counts = _summary_counts(output)
    if counts["failed"] or counts["error"]:
        raise ConformanceGateError(
            f"conformance gate did not pass cleanly: {counts}"
        )
    if counts["passed"] < minimum_passed:
        raise ConformanceGateError(
            f"conformance gate ran {counts['passed']} case(s) (minimum "
            f"{minimum_passed}); {counts['skipped']} skipped. An all-skip run "
            f"means importorskip fired against a missing/wrong kit module — the "
            f"gate enforced nothing. See docs/cli-contract.md §7 (WI-026)."
        )
    return counts


def _run_pytest(test_path: Path, tmp_path: Path) -> str:
    """Run pytest on ``test_path`` and return combined stdout+stderr."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(test_path),
            "-q", "-p", "no:cacheprovider", "--no-header",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return proc.stdout + proc.stderr


def test_conformance_gate_runs_at_least_one_case(tmp_path: Path) -> None:
    """The live conformance module must pass >=1 case (not all-skip).

    If a future kit rename or layout change makes ``importorskip`` fire again,
    this assertion goes red — the structural cure for the 2026-07-24 bug.
    """
    output = _run_pytest(CONFORMANCE_TEST, tmp_path)
    counts = require_gate_ran(output, minimum_passed=1)
    assert counts["passed"] >= 1, counts


def test_require_gate_ran_accepts_a_passing_summary() -> None:
    """Positive control: a normal summary passes the guard."""
    counts = require_gate_ran("..........                               [100%]\n10 passed in 1.24s\n")
    assert counts["passed"] == 10


def test_require_gate_ran_rejects_an_all_skip_summary() -> None:
    """Deny case: an all-skip summary (importorskip fired) must be rejected."""
    with pytest.raises(ConformanceGateError, match="importorskip"):
        require_gate_ran("s.....                                   [100%]\n5 skipped in 0.5s\n")


def test_require_gate_ran_rejects_failures() -> None:
    """Deny case: a failing run must not be papered over as 'gate ran'."""
    with pytest.raises(ConformanceGateError, match="did not pass cleanly"):
        require_gate_ran("F                                        [100%]\n1 failed in 0.5s\n")


def test_meta_guard_detects_a_real_importorskip_skip(tmp_path: Path) -> None:
    """End-to-end falsifier: a module that importorskip's a bogus name produces
    an all-skip summary, and ``require_gate_ran`` flags it. This proves the guard
    genuinely catches the skip class, not just a hand-written summary string."""
    bogus = tmp_path / "test_skips_silently.py"
    bogus.write_text(
        "import pytest\n"
        "pytest.importorskip('agent_suite.conformance.this_does_not_exist_xyz')\n"
        "def test_dummy() -> None:\n"
        "    assert False  # would fail if it ran; it must not run\n"
    )
    output = _run_pytest(bogus, tmp_path)
    with pytest.raises(ConformanceGateError, match="importorskip"):
        require_gate_ran(output, minimum_passed=1)
