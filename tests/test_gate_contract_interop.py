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

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest
from packaging.version import InvalidVersion, Version

from agent_suite.config import postgres_database_fingerprint
from agent_suite.genesis_gate import (
    _ACTOR_BOUNDARY_BASIS,
    _ACTOR_BOUNDARY_CHECK_ID,
    _ACTOR_BOUNDARY_CLAIM,
    _ACTOR_BOUNDARY_EXCLUSIONS,
    _ACTOR_BOUNDARY_PATHS,
    _ACTOR_BOUNDARY_RESIDUAL_TOKEN,
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
    _regista_available,
    _require_interop,
)

# ---------------------------------------------------------------------------
# Lane gating
# ---------------------------------------------------------------------------

_SKIP_REASON = (
    "Gate-contract interop prerequisites not met — need regista + (Docker or "
    "INTEROP_DSN env). In the interop lane (INTEROP_REQUIRE_FACES=1) this "
    "module does not skip; it fails — including from underneath, via "
    "conftest's shared _fail_or_skip."
)

#: Whether the live-probe tests below should skip: no blanket module-level
#: ``pytestmark`` (WI-084 item 4) because the reverse-direction pin further
#: down needs no probe, no store and no regista, so it must not share a gate
#: that exists for tests which do. Applied individually to each test that
#: actually needs the prerequisites instead.
_MODULE_SKIP = not _can_run() and not _require_interop()

#: The component that owns the actor-boundary check, per the gate's own
#: ownership map — i.e. the spine, derived from the very check this module
#: exists to pin rather than spelled out again. A component name repeated here
#: is one more literal that can drift from ``genesis_gate``.
_SPINE: str = GENESIS_REQUIRED_CHECK_OWNERS[_ACTOR_BOUNDARY_CHECK_ID]

#: The gate's own spec for the spine — command, required check IDs and all.
#: Taken from ``PROBE_SPECS`` so the test cannot run a different argv than the
#: gate does, which is precisely the drift the regista-side guard also pins.
_REGISTA_SPEC: ProbeSpec = next(
    spec for spec in PROBE_SPECS if spec.component == _SPINE
)

#: Required checks the gate expects from components other than the spine. They
#: are absent by construction here (only the spine's probe is run), so they are
#: the *complete* expected failure set for the evaluation below — derived, not
#: transcribed, so adding a component to the gate cannot silently widen it.
_NON_REGISTA_REQUIRED = frozenset(
    check_id
    for check_id, owner in GENESIS_REQUIRED_CHECK_OWNERS.items()
    if owner != _SPINE
)

#: libpq's ambient connection variables. Scrubbed alongside ``REGISTA_*``
#: before the probe runs: ``PGHOST``/``PGDATABASE``/``PGSERVICE`` and friends
#: are consulted by psycopg for any connection parameter the DSN leaves out, so
#: an operator's exported ``PGDATABASE`` could redirect part of the probe's
#: connection away from the throwaway store while the comparison below still
#: read green.
_LIBPQ_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGPASSFILE",
    "PGDATABASE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSSLMODE",
    "PGOPTIONS",
)


# ---------------------------------------------------------------------------
# Reverse-direction pin (WI-084 item 4)
# ---------------------------------------------------------------------------
#
# Everything above proves the installed regista satisfies whatever the gate
# *currently* demands. None of it notices the gate demanding less: deleting a
# required check from a ``PROBE_SPECS`` entry, or re-owning a
# ``regista.*`` check to a different component in
# ``GENESIS_REQUIRED_CHECK_OWNERS``, leaves every test above green — the live
# probe would simply be asked to prove a smaller contract, and it would.
# ``_SPINE`` / ``_REGISTA_SPEC`` / ``_NON_REGISTA_REQUIRED`` above are
# deliberately *derived* from ``genesis_gate``'s own constants (so a new
# component can't silently widen the expected failure set) — but that same
# derivation means they cannot catch the gate's constants shrinking, because
# they shrink right along with them. Catching that needs an independent,
# hand-transcribed second copy, the same "we forgot vs. we decided" ritual
# ``DOSSIER_VARS_NOT_IN_SUITE_ENV`` uses (tests/test_config_surface.py).
#
# Update ritual: changing ``GENESIS_REQUIRED_CHECK_OWNERS`` or a
# ``ProbeSpec.required_checks`` in ``genesis_gate.py`` is a real contract
# change. Update the two pins below IN THE SAME COMMIT and say why in the
# commit message ("we decided" a check is no longer required, or ownership
# moved) — so a change here is always a deliberate, reviewed edit to this
# file, never a side effect of editing ``genesis_gate.py`` alone.

#: Independent snapshot of ``GENESIS_REQUIRED_CHECK_OWNERS``. Catches a check
#: silently dropped, silently re-owned, or a component renamed.
_PINNED_REQUIRED_CHECK_OWNERS: Mapping[str, str] = {
    "regista.load_bearing_fields_refused": "regista",
    "regista.closed_lineage_registry": "regista",
    "regista.first_write_admission": "regista",
    "regista.actor_boundary_signing": "regista",
    "cairn.runtime_model_observed": "cairn",
    "cairn.unavailable_model_named": "cairn",
    "cairn.observation_failure_nonblocking": "cairn",
    "agent_notes.session_identity_resolvable": "agent-notes",
}

#: Independent snapshot of each ``ProbeSpec.required_checks``, keyed by
#: component. Catches a check quietly dropped from a spec's required set even
#: where ``GENESIS_REQUIRED_CHECK_OWNERS`` is untouched (the two are not the
#: same mapping — ``store_invariant_measurements`` is required of the regista
#: probe but is not an owned pass/fail check, so it has no owner entry).
_PINNED_PROBE_REQUIRED_CHECKS: Mapping[str, frozenset[str]] = {
    "regista": frozenset(
        {
            "regista.store_invariant_measurements",
            "regista.load_bearing_fields_refused",
            "regista.closed_lineage_registry",
            "regista.first_write_admission",
            "regista.actor_boundary_signing",
        }
    ),
    "cairn": frozenset(
        {
            "cairn.runtime_model_observed",
            "cairn.unavailable_model_named",
            "cairn.observation_failure_nonblocking",
        }
    ),
    "agent-notes": frozenset({"agent_notes.session_identity_resolvable"}),
}


def test_genesis_required_check_spec_has_not_been_quietly_weakened() -> None:
    """agent-suite weakening its own spec must redden this module too.

    Pure comparison against ``genesis_gate``'s live constants — no probe, no
    store, no regista needed — so it runs (and can fail) even in an
    environment with none of those prerequisites, unlike every other test in
    this module. See the module comment above for what this catches and the
    ritual for updating the pin on a deliberate contract change.
    """
    assert dict(GENESIS_REQUIRED_CHECK_OWNERS) == dict(_PINNED_REQUIRED_CHECK_OWNERS), (
        "GENESIS_REQUIRED_CHECK_OWNERS drifted from the pinned snapshot — a "
        "check was added/removed, or its owner changed. If this is "
        "deliberate, update _PINNED_REQUIRED_CHECK_OWNERS in the same commit "
        f"and say why. live={dict(GENESIS_REQUIRED_CHECK_OWNERS)!r} "
        f"pinned={dict(_PINNED_REQUIRED_CHECK_OWNERS)!r}"
    )
    live_required_checks = {spec.component: spec.required_checks for spec in PROBE_SPECS}
    assert live_required_checks == dict(_PINNED_PROBE_REQUIRED_CHECKS), (
        "A ProbeSpec's required_checks drifted from the pinned snapshot — a "
        "required check was added/removed for some component, or a component "
        "was added/removed from PROBE_SPECS entirely. If this is deliberate, "
        "update _PINNED_PROBE_REQUIRED_CHECKS in the same commit and say why. "
        f"live={live_required_checks!r} pinned={dict(_PINNED_PROBE_REQUIRED_CHECKS)!r}"
    )


# ---------------------------------------------------------------------------
# The live probe
# ---------------------------------------------------------------------------


def _assert_versions_match(reported: str | None, imported: str, *, resolved_path: Path) -> None:
    """Cross-check the probe's self-reported version against the imported package.

    Strict string equality (WI-084 item 3) misdiagnoses one real case: a
    dev/editable build whose runtime ``__version__`` carries a PEP 440 local
    segment (``+dirty``, ``+g<sha>``, …) that the wheel's static METADATA
    ``Version`` field never had, even though both describe the same release.
    Parsing with ``packaging.version.Version`` lets that case be named
    precisely instead of reported as an opaque string mismatch.

    Chosen reading (documented per WI-084 item 3, "pick the stricter
    reasonable reading"): a difference confined to the local segment is
    *still a failure* — this repo's convention is to prefer strict defaults,
    and silently normalizing local segments away would let the probe binary
    and the imported package come from two different local builds of the
    same release without comment. The only thing parsing buys is a sharper
    error message that tells the two cases apart.
    """
    if reported == imported:
        return
    try:
        reported_v = Version(reported) if reported is not None else None
        imported_v = Version(imported)
    except InvalidVersion:
        reported_v = None
        imported_v = None
    if reported_v is not None and imported_v is not None and reported_v.public == imported_v.public:
        pytest.fail(
            f"{resolved_path} reports library_version {reported!r}, whose public "
            f"version matches the imported distribution's {imported!r} but whose "
            f"local segment does not ({reported_v.local!r} vs {imported_v.local!r}). "
            "Strict comparison (WI-084 item 3): a local-segment-only difference is "
            "still treated as a mismatch, not normalized away — the probe binary "
            "and the imported package were built from different local revisions "
            "(e.g. one dirty checkout, one clean), so the contract would be "
            "compared against an unpinned local build."
        )
    pytest.fail(
        f"{resolved_path} reports library_version {reported!r} but the imported "
        f"distribution is {imported!r} — the probe and the store would come from "
        "different installs."
    )


def _assert_probe_binary_is_the_installed_spine() -> str:
    """Resolve the probe's executable and prove it is *this* environment's spine.

    Two separate installs answer to the name ``regista`` on a developer box: the
    one this venv imports, and whatever a user-level tool install
    (``~/.local/bin``) put earlier on ``PATH``. The gate resolves its probe by
    ``shutil.which``, but the store below is provisioned by the *imported*
    package — nothing in the report reconciles them, and the probe JSON carries
    no version field to reconcile them with. A stale uv-tool shim on ``PATH``
    therefore silently turns this module into a contract comparison against a
    different release than the one under test. That is not hypothetical: a
    0.6.0 shim shadowed the 0.7.2 venv install in an independent review of this
    very file.

    So pin on the resolved *path* — it must live inside ``sys.prefix`` — and
    then reconcile the two versions across the process boundary: the
    distribution backing the imported ``regista`` package, and the
    ``library_version`` the resolved script reports for itself.

    Uses ``pytest.fail`` throughout rather than a bare ``assert`` (WI-084 item
    3): this function runs unconditionally, including under ``python -O``,
    where a bare ``assert`` is compiled out and the guard would silently do
    nothing.
    """
    probe_executable = _REGISTA_SPEC.command[0]
    # which() resolves the exact executable name the gate's own runner
    # invokes (WI-084 item 2) — ``_SPINE`` (the *component* name from
    # GENESIS_REQUIRED_CHECK_OWNERS) coincides with it for regista today, but
    # nothing enforces that, and packages_distributions() below keys on a
    # third, independent name (the *import* name). Resolving the wrong one of
    # the three would validate a binary the gate would never actually run.
    resolved = shutil.which(probe_executable)
    if resolved is None:
        pytest.fail(
            f"no {probe_executable!r} executable on PATH, so the gate's frozen "
            "contract would be compared against nothing."
        )
    resolved_path = Path(resolved).resolve()
    prefix = Path(sys.prefix).resolve()
    if not resolved_path.is_relative_to(prefix):
        pytest.fail(
            f"PATH resolves {probe_executable!r} to {resolved_path}, which is "
            f"OUTSIDE this environment ({prefix}). The store is provisioned by "
            f"the imported package while the probe would run that other "
            f"install, so the contract comparison would be against an unpinned "
            f"release. Run under `uv run --frozen`, or remove the shadowing "
            f"entry from PATH."
        )

    # packages_distributions() keys on *import* names (e.g. ``agent_notes``),
    # not component or command names — for regista today all three coincide,
    # which is exactly the coincidence item 2 warns not to lean on elsewhere.
    distributions = importlib.metadata.packages_distributions().get(_SPINE, [])
    # Indexing distributions[0] would be order-dependent if more than one
    # distribution ever claimed this import name (WI-084 item 3) — assert
    # there is exactly one instead of silently picking a side.
    if len(distributions) != 1:
        pytest.fail(
            f"expected exactly one distribution backing the imported {_SPINE!r} "
            f"package, found {distributions!r}. packages_distributions()[...][0] "
            "would pick one arbitrarily, which is not a version this test can "
            "stand behind."
        )
    imported_version = importlib.metadata.version(distributions[0])
    completed = subprocess.run(
        (str(resolved_path), "version", "--json"),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    reported_version = json.loads(completed.stdout).get("library_version")
    _assert_versions_match(reported_version, imported_version, resolved_path=resolved_path)
    return imported_version


@pytest.fixture(scope="module")
def _verified_probe_binary() -> None:
    """Hoisted ahead of ``probe_project``'s own work (WI-084 item 3).

    ``_assert_probe_binary_is_the_installed_spine`` used to run as the first
    line of ``live_probe_report``, i.e. *after* ``probe_project`` had already
    paid for standing up a project across the v6 genesis boundary (~4s of
    Postgres round-trips and ~50 migrations) — work this module does not need
    when the answer is "wrong regista on PATH". Listed as ``probe_project``'s
    *first* parameter below rather than made autouse: autouse would also pull
    in a regista-CLI dependency for the reverse-direction pin test further
    down, which needs none of this module's prerequisites at all. Same-scope
    fixtures with no dependency on each other are set up in the order the
    requesting fixture lists them, so this still runs before ``interop_dsn``
    and the rest of ``probe_project``'s body for every test that reaches it —
    a stale PATH shim now fails in milliseconds instead of seconds.
    """
    _assert_probe_binary_is_the_installed_spine()


@pytest.fixture(scope="module")
def probe_project(
    _verified_probe_binary: None, interop_dsn: str, tmp_path_factory: pytest.TempPathFactory
) -> Generator[str, None, None]:
    """A disposable, empty regista project for the probe to measure.

    Empty and *pre-genesis* on purpose: that is the store state a real
    qualification ceremony gates on, so the measurement findings the evaluator
    derives below are the ones an operator would actually see.

    Disposable Ed25519 key material in a per-module temp dir — never a tracked
    fixture file and never the operator's key path.
    """
    if not _regista_available():
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

    Which executable ``shutil.which`` will land on is pinned before
    ``probe_project`` does any of its own work — see the ``_verified_probe_binary``
    fixture above.

    Every ambient ``REGISTA_*`` and ``PG*`` variable is then dropped. The
    operator's own DSN, project or key path leaking into a measurement of a
    throwaway project would mean the probe reported on the wrong store, and the
    contract comparison would still look green.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in [key for key in os.environ if key.startswith("REGISTA_")]:
            mp.delenv(name, raising=False)
        for name in _LIBPQ_ENV:
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


@pytest.mark.skipif(_MODULE_SKIP, reason=_SKIP_REASON)
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


@pytest.mark.skipif(_MODULE_SKIP, reason=_SKIP_REASON)
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


@pytest.mark.skipif(_MODULE_SKIP, reason=_SKIP_REASON)
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
    assert isinstance(reason, str) and _ACTOR_BOUNDARY_RESIDUAL_TOKEN in reason, (
        f"the emitted check no longer names the {_ACTOR_BOUNDARY_RESIDUAL_TOKEN} "
        f"residual: {reason!r}"
    )

    # The real validator last: everything above is diagnosis, this is the verdict.
    assert _actor_boundary_contract_error(check) is None


@pytest.mark.skipif(_MODULE_SKIP, reason=_SKIP_REASON)
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
