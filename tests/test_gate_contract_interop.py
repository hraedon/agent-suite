"""Consumer-side interop: the frozen gate contract vs. the installed spine.

``agent_suite.genesis_gate`` does not merely require that regista's invariant
probe emits a ``regista.actor_boundary_signing`` check. It freezes that check's
*content* — the scoped R-10 claim string, the evidence basis, and three exact
path sets — and calls the whole report MALFORMED when any of them differs
(``_actor_boundary_contract_error``). Those are cross-repo literals held in
this repo about a report another repo writes.

Nothing on this side ever compared them against a real probe. regista renamed
the claim late in its 0.7.2 cycle; agent-suite's stale expectation then made
genuine qualification reports evaluate as MALFORMED, and the only thing that
caught it was a live qualification ceremony. The one automated guard lives in
regista (``tests/test_wi326_probe_gate_contract.py``) and it is **path-coupled**:
it loads this repo's validator from a hard-coded ``/projects/agent-suite/src``
and skips when that directory is absent — which is every CI runner and every
box that does not happen to keep the two checkouts side by side. Consumer-side,
the contract was unverified.

This module closes that gap from the consumer side, at the strongest available
level: it runs the **real** probe — the same argv the ceremony runs, through
the gate's own :func:`run_invariant_probes` and its default runner and
installed-check — against a disposable, empty project on the interop lane's
Postgres, and puts the real stdout through the real parser
(``_parse_probe_result``) and the real evaluator (``evaluate_genesis_gate``).
Every expectation is read from ``genesis_gate``'s own constants rather than
transcribed: a second copy of the contract is a second thing that can drift.

**Fail-closed.** In the interop lane (``INTEROP_REQUIRE_FACES=1``, set by the
``interop`` CI job) this module never skips. A missing regista, an unrunnable
probe, or a probe that cannot reach the store is a hard failure — "the contract
was not checked" and "the contract holds" must not look alike, which is the
same fails-open class as the regista-side guard's silent skip. Outside that
lane it skips like the other integration modules when there is no regista and
no Postgres.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from typing import Any

import pytest

from agent_suite.config import postgres_database_fingerprint
from agent_suite.genesis_gate import (
    _ACTOR_BOUNDARY_BASIS,
    _ACTOR_BOUNDARY_CHECK_ID,
    _ACTOR_BOUNDARY_CLAIM,
    _ACTOR_BOUNDARY_EXCLUSIONS,
    _ACTOR_BOUNDARY_PATHS,
    _ACTOR_BOUNDARY_SHARED_CONSUMERS,
    GENESIS_REQUIRED_CHECK_OWNERS,
    PROBE_SPECS,
    InvariantProbeReport,
    ProbeResult,
    ProbeSpec,
    ProbeStatus,
    _actor_boundary_contract_error,
    evaluate_genesis_gate,
    run_invariant_probes,
)
from tests.conftest import (
    V6_BOOTSTRAP_PRINCIPAL,
    _can_run,
    _generate_v6_keyset,
)

# ---------------------------------------------------------------------------
# Lane gating
# ---------------------------------------------------------------------------

#: The interop lane's own marker. ``INTEROP_REQUIRE_FACES=1`` is set only by
#: the ``interop`` CI job, and ``conftest.regista_project`` already reads it as
#: "this is the lane where a missing prerequisite is a regression, not an
#: optional proof". Reused rather than inventing a second flag, so there is one
#: switch for the lane and not two that can disagree.
_REQUIRE_INTEROP = os.environ.get("INTEROP_REQUIRE_FACES", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

_SKIP_REASON = (
    "Gate-contract interop prerequisites not met — need regista + (Docker or "
    "INTEROP_DSN env). In the interop lane (INTEROP_REQUIRE_FACES=1) this "
    "module does not skip; it fails."
)

pytestmark = pytest.mark.skipif(
    not _can_run() and not _REQUIRE_INTEROP, reason=_SKIP_REASON
)

#: The gate's own spec for the spine — command, required check IDs and all.
#: Taken from ``PROBE_SPECS`` so the test cannot run a different argv than the
#: gate does, which is precisely the drift the regista-side guard also pins.
_REGISTA_SPEC: ProbeSpec = next(
    spec for spec in PROBE_SPECS if spec.component == "regista"
)

#: Required checks the gate expects from components other than regista. They
#: are absent by construction here (only the spine's probe is run), so they are
#: the *complete* expected failure set for the evaluation below — derived, not
#: transcribed, so adding a component to the gate cannot silently widen it.
_NON_REGISTA_REQUIRED = frozenset(
    check_id
    for check_id, owner in GENESIS_REQUIRED_CHECK_OWNERS.items()
    if owner != "regista"
)


# ---------------------------------------------------------------------------
# The live probe
# ---------------------------------------------------------------------------


def _regista_importable() -> bool:
    try:
        import regista  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="module")
def probe_project(
    interop_dsn: str, tmp_path_factory: pytest.TempPathFactory
) -> Generator[str, None, None]:
    """A disposable, empty regista project for the probe to measure.

    Empty and *pre-genesis* on purpose: that is the store state a real
    qualification ceremony gates on, so the measurement findings the evaluator
    derives below are the ones an operator would actually see.

    Disposable Ed25519 key material in a per-module temp dir — never a tracked
    fixture file and never the operator's key path.
    """
    if not _regista_importable():
        pytest.fail(
            "regista is not importable, so the gate's frozen contract could "
            "not be compared against any real probe output. In the interop "
            "lane this is a spine-install regression; it must not be a skip."
        )

    from regista import Regista
    from regista.testing import drop_project_schema

    keyset = _generate_v6_keyset(
        tmp_path_factory.mktemp("gate-contract"),
        (V6_BOOTSTRAP_PRINCIPAL,),
        filename="gate_contract_v6_keys.json",
    )
    project = f"gatecontract_{uuid.uuid4().hex[:8]}"
    sub = Regista.create_project(interop_dsn, project, keyset.path)
    try:
        yield project
    finally:
        sub.close()
        drop_project_schema(interop_dsn, project)


@pytest.fixture(scope="module")
def live_probe_report(interop_dsn: str, probe_project: str) -> InvariantProbeReport:
    """The gate's own probe runner, over the real console script, once.

    ``run_invariant_probes`` is called with its **default** runner and
    installed-check — no injected doubles — so what is exercised is the exact
    path ``agent-suite genesis-gate`` takes: ``shutil.which('regista')``, then
    ``subprocess.run(('regista', 'invariants', 'probe', '--json'))``, then
    ``_parse_probe_result``.

    Every ambient ``REGISTA_*`` variable is dropped before the run. The
    operator's own DSN, project or key path leaking into a measurement of a
    throwaway project would mean the probe reported on the wrong store, and the
    contract comparison would still look green.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in [key for key in os.environ if key.startswith("REGISTA_")]:
            mp.delenv(name, raising=False)
        mp.setenv("REGISTA_DSN", interop_dsn)
        mp.setenv("REGISTA_PROJECT", probe_project)
        return run_invariant_probes(specs=(_REGISTA_SPEC,))


def _regista_result(report: InvariantProbeReport) -> ProbeResult:
    assert len(report.probes) == 1, f"expected one probe result, got {report.probes}"
    return report.probes[0]


def _boundary_check(report: InvariantProbeReport) -> dict[str, Any]:
    result = _regista_result(report)
    for check in result.checks:
        if check.get("id") == _ACTOR_BOUNDARY_CHECK_ID:
            return check
    raise AssertionError(
        f"the installed regista emitted no {_ACTOR_BOUNDARY_CHECK_ID!r} check. "
        f"Emitted: {sorted(str(check.get('id')) for check in result.checks)}"
    )


# ---------------------------------------------------------------------------
# The proofs
# ---------------------------------------------------------------------------


def test_the_real_probe_is_not_malformed_against_the_frozen_contract(
    live_probe_report: InvariantProbeReport,
) -> None:
    """The whole point: real spine output, real parser, and it must not be MALFORMED.

    A stale frozen literal in ``genesis_gate`` shows up here exactly as it
    showed up in the live ceremony — as MALFORMED with the offending field
    named in ``detail`` — rather than only in a hand-built fixture that agrees
    with the constants by construction.
    """
    result = _regista_result(live_probe_report)
    assert result.status is not ProbeStatus.MISSING, (
        "the 'regista' console script is not on PATH, so the frozen gate "
        "contract was compared against nothing. Install the SUITE.lock-pinned "
        "spine into the test environment."
    )
    assert result.status is ProbeStatus.PASS, (
        f"the installed regista's real probe output does not satisfy the gate's "
        f"frozen contract: [{result.status.value}] {result.detail}"
    )
    assert live_probe_report.ok


def test_every_gate_required_check_id_is_emitted_by_the_installed_spine(
    live_probe_report: InvariantProbeReport,
) -> None:
    """``ProbeSpec.required_checks`` names IDs another repo owns.

    ``_parse_probe_result`` turns a missing one into MALFORMED, which is
    correct but reports the whole report as bad; this names the drifted IDs
    directly so a rename is diagnosed rather than merely detected.
    """
    emitted = {
        str(check["id"])
        for check in _regista_result(live_probe_report).checks
        if isinstance(check.get("id"), str)
    }
    missing = sorted(_REGISTA_SPEC.required_checks - emitted)
    assert not missing, (
        f"agent-suite's PROBE_SPECS requires check IDs the installed regista "
        f"does not emit: {', '.join(missing)}. Emitted: {sorted(emitted)}"
    )


def test_the_frozen_actor_boundary_contract_matches_the_emitted_check(
    live_probe_report: InvariantProbeReport,
) -> None:
    """Field by field, so a drift names which frozen literal went stale.

    ``_actor_boundary_contract_error`` is the real validator and is asserted
    first, but its message is deliberately coarse ("changed its scoped claim").
    The per-field assertions below exist so the failure output carries both
    sides of the disagreement — what this repo froze and what the installed
    spine actually emitted.
    """
    check = _boundary_check(live_probe_report)

    assert check.get("claim") == _ACTOR_BOUNDARY_CLAIM, (
        f"frozen claim {_ACTOR_BOUNDARY_CLAIM!r} != emitted {check.get('claim')!r}"
    )
    assert check.get("basis") == _ACTOR_BOUNDARY_BASIS, (
        f"frozen basis {_ACTOR_BOUNDARY_BASIS!r} != emitted {check.get('basis')!r}"
    )
    for field, frozen in (
        ("paths_proven", _ACTOR_BOUNDARY_PATHS),
        ("shared_boundary_consumers", _ACTOR_BOUNDARY_SHARED_CONSUMERS),
        ("excluded_paths", _ACTOR_BOUNDARY_EXCLUSIONS),
    ):
        emitted = check.get(field)
        assert isinstance(emitted, list) and all(
            isinstance(item, str) for item in emitted
        ), f"{field}: expected a list of strings, got {emitted!r}"
        # Length as well as membership: the gate refuses a duplicated entry
        # too, so a set comparison alone would not reproduce its verdict.
        assert len(emitted) == len(frozen) and frozenset(emitted) == frozen, (
            f"{field} drifted — frozen {sorted(frozen)}, emitted {emitted}"
        )
    reason = check.get("exclusion_reason")
    assert isinstance(reason, str) and "WI-320" in reason, (
        f"the emitted check no longer names the WI-320 residual: {reason!r}"
    )

    # The real validator last: everything above is diagnosis, this is the verdict.
    assert _actor_boundary_contract_error(check) is None


def test_the_evaluator_accepts_the_whole_live_regista_contribution(
    live_probe_report: InvariantProbeReport, interop_dsn: str, probe_project: str
) -> None:
    """The gate's public evaluator over the real report, bound to the real store.

    ``_parse_probe_result`` is one of two places the scoped contract is
    enforced; ``evaluate_genesis_gate`` re-checks it independently on the
    required-check pass, and that is the one whose verdict an operator sees. So
    the real report is evaluated here with the same binding inputs
    ``agent-suite genesis-gate`` derives from the environment.

    Asserting that the failing findings are *exactly* the other components'
    required checks is stronger than asserting the boundary finding passed: it
    pins the store fingerprint agreement (this repo computes the expected
    fingerprint, regista computes the reported one — two implementations that
    must produce the same digest), the project and snapshot binding, and every
    pre-genesis measurement predicate, all against a real store.
    """
    report = evaluate_genesis_gate(
        live_probe_report,
        expected_store_fingerprint=postgres_database_fingerprint(interop_dsn),
        expected_project=probe_project,
    )

    boundary = [
        finding
        for finding in report.findings
        if finding.check_id == _ACTOR_BOUNDARY_CHECK_ID
    ]
    assert len(boundary) == 1, f"expected one boundary finding, got {boundary}"
    assert boundary[0].status is ProbeStatus.PASS, boundary[0].detail

    failed = {
        finding.check_id
        for finding in report.findings
        if finding.status is not ProbeStatus.PASS
    }
    assert failed == _NON_REGISTA_REQUIRED, (
        "the only findings that may fail here are the required checks owned by "
        "components this test does not probe. Unexpected failures: "
        f"{sorted(failed - _NON_REGISTA_REQUIRED)}; unexpectedly passing: "
        f"{sorted(_NON_REGISTA_REQUIRED - failed)}"
    )
