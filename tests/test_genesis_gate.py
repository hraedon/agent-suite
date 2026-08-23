from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest

from agent_suite.genesis_gate import (
    GENESIS_REQUIRED_CHECK_OWNERS,
    GENESIS_REQUIRED_CHECKS,
    PROBE_SPECS,
    ProbeSpec,
    ProbeStatus,
    evaluate_genesis_gate,
    run_invariant_probes,
)

_PASSING_SPECS = PROBE_SPECS
_STORE_FINGERPRINT = "sha256:" + "a" * 64
_PROJECT = "throwaway"


def _clean_measurement() -> dict[str, object]:
    return {
        "project": _PROJECT,
        "snapshot_id": "pg:10:20:",
        "event_count": 0,
        "declared_lineage_event_count": 0,
        "lineage_coverage": {"numerator": 0, "denominator": 0},
        "distinct_lineage_tokens": [],
        "unresolvable_lineage_tokens": [],
        "unresolvable_lineage_value_count": 0,
        "ambiguous_lineage_event_count": 0,
        "scheme_counts": {},
        "undeclared_agent_author_event_count": 0,
        "model_observation_status_counts": {},
    }


def _passing_bodies() -> dict[str, dict[str, object]]:
    return {
        "regista": {
            "component": "regista",
            "probe_version": 1,
            "ok": True,
            "checks": [
                {
                    "id": "regista.store_invariant_measurements",
                    "status": "measured",
                    "store_fingerprint": _STORE_FINGERPRINT,
                    "projects": [_clean_measurement()],
                    "errors": [],
                },
                {"id": "regista.load_bearing_fields_refused", "status": "pass"},
                {"id": "regista.closed_lineage_registry", "status": "pass"},
                {"id": "regista.first_write_admission", "status": "pass"},
                {
                    "id": "regista.actor_boundary_signing",
                    "status": "pass",
                    "claim": "r10.project_v6.boundary_rejects_mismatched_binding",
                    "basis": "behavioral_attempt_ephemeral_epoch",
                    "paths_proven": [
                        "regista._genesis.append_v6_genesis",
                        "regista._v6_writer.append_v6_event",
                    ],
                    "shared_boundary_consumers": [
                        "regista._trust_log_writer.append_trust_log_event"
                    ],
                    "excluded_paths": [
                        "regista._cli.cmd_trust_init_log",
                        "regista._cli.cmd_trust_delegate_registrar",
                        "regista._cli._resolve_trust_root_actor",
                        "regista._trust_log_writer.write_trust_genesis",
                    ],
                    "exclusion_reason": "WI-320 remains explicit",
                },
            ],
        },
        "cairn": {
            "component": "cairn",
            "probe_version": 1,
            "ok": True,
            "checks": [
                {"id": "cairn.runtime_model_observed", "status": "pass"},
                {"id": "cairn.unavailable_model_named", "status": "pass"},
                {"id": "cairn.observation_failure_nonblocking", "status": "pass"},
            ],
        },
        "agent-notes": {
            "component": "agent-notes",
            "probe_version": 1,
            "ok": True,
            "checks": [
                {"id": "agent_notes.session_identity_resolvable", "status": "pass"},
            ],
        },
    }


def _run_bodies(bodies: dict[str, dict[str, object]]):
    by_executable = {spec.command[0]: spec.component for spec in _PASSING_SPECS}

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        component = by_executable[command[0]]
        body = bodies[component]
        return subprocess.CompletedProcess(
            command,
            0 if body.get("ok") is True else 1,
            stdout=json.dumps(body),
            stderr="",
        )

    return run_invariant_probes(
        specs=_PASSING_SPECS,
        runner=runner,
        installed=lambda _executable: True,
    )


def _evaluate(bodies: dict[str, dict[str, object]]):
    return evaluate_genesis_gate(
        _run_bodies(bodies),
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )


def test_throwaway_pass_fixture_opens_gate() -> None:
    probes = _run_bodies(_passing_bodies())
    gate = evaluate_genesis_gate(
        probes,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert probes.ok is True
    assert gate.ok is True
    assert gate.to_dict()["epoch_may_open"] is True


@pytest.mark.parametrize("check_id", sorted(GENESIS_REQUIRED_CHECKS))
def test_each_required_behavior_has_a_deny_case(check_id: str) -> None:
    bodies = _passing_bodies()
    for body in bodies.values():
        body["checks"] = [
            check for check in body["checks"] if check["id"] != check_id  # type: ignore[index]
        ]

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(item for item in gate.findings if item.check_id == check_id)
    assert finding.status is ProbeStatus.FAIL


def test_actor_boundary_signing_missing_blocks_gate() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"] = [
        check
        for check in bodies["regista"]["checks"]  # type: ignore[union-attr]
        if check["id"] != "regista.actor_boundary_signing"
    ]

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(
        item for item in gate.findings if item.check_id == "regista.actor_boundary_signing"
    )
    assert finding.status is ProbeStatus.FAIL
    assert "absent" in finding.detail


def test_actor_boundary_signing_failure_blocks_gate() -> None:
    bodies = _passing_bodies()
    signing = next(
        check
        for check in bodies["regista"]["checks"]  # type: ignore[union-attr]
        if check["id"] == "regista.actor_boundary_signing"
    )
    signing["status"] = "fail"
    bodies["regista"]["ok"] = False

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(
        item for item in gate.findings if item.check_id == "regista.actor_boundary_signing"
    )
    assert finding.status is ProbeStatus.FAIL
    assert "reported failure" in finding.detail


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("claim", None),
        ("claim", "r10.full"),
        ("claim", "r10.no_arbitrary_principal.project_v6"),
        ("basis", "configuration_inspection"),
        ("paths_proven", ["regista._v6_writer.append_v6_event"]),
        ("shared_boundary_consumers", []),
        ("excluded_paths", []),
        ("exclusion_reason", "residual omitted"),
    ],
)
def test_actor_boundary_scope_contract_fails_closed(field: str, bad_value: object) -> None:
    bodies = _passing_bodies()
    signing = next(
        check
        for check in bodies["regista"]["checks"]  # type: ignore[union-attr]
        if check["id"] == "regista.actor_boundary_signing"
    )
    signing[field] = bad_value

    probes = _run_bodies(bodies)
    regista = next(probe for probe in probes.probes if probe.component == "regista")

    assert regista.status is ProbeStatus.MALFORMED
    assert "actor_boundary_signing" in regista.detail


def test_malformed_owner_probe_cannot_supply_a_passing_gate_check() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"].append(  # type: ignore[union-attr]
        {"id": "regista.closed_lineage_registry", "status": "pass"}
    )

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(
        item for item in gate.findings if item.check_id == "regista.actor_boundary_signing"
    )
    assert finding.status is ProbeStatus.FAIL
    assert "did not pass contract validation" in finding.detail


@pytest.mark.parametrize(
    ("field", "bad_value", "finding_prefix"),
    [
        ("event_count", 1, "regista.store_empty"),
        ("unresolvable_lineage_tokens", ["GLM-5.2"], "regista.lineage_tokens_resolvable"),
        ("unresolvable_lineage_value_count", 1, "regista.lineage_tokens_resolvable"),
        ("ambiguous_lineage_event_count", 1, "regista.lineage_unambiguous"),
        ("scheme_counts", {"hmac-sha256": 1}, "regista.asymmetric_only"),
        ("scheme_counts", None, "regista.asymmetric_only"),
        ("undeclared_agent_author_event_count", 1, "regista.authors_declared"),
        ("declared_lineage_event_count", 1, "regista.lineage_population_empty"),
        (
            "lineage_coverage",
            {"numerator": 1, "denominator": 1},
            "regista.lineage_population_empty",
        ),
        ("distinct_lineage_tokens", ["glm"], "regista.lineage_population_empty"),
        (
            "model_observation_status_counts",
            {"observed": 1},
            "regista.model_observation_population_empty",
        ),
        ("event_count", 0.0, "regista.store_empty"),
        # bool is a subclass of int and False == 0; the predicates must
        # reject it via the exact `type(...) is int` check.
        ("undeclared_agent_author_event_count", False, "regista.authors_declared"),
    ],
)
def test_each_store_predicate_has_a_deny_case(
    field: str,
    bad_value: object,
    finding_prefix: str,
) -> None:
    bodies = deepcopy(_passing_bodies())
    measurement = bodies["regista"]["checks"][0]["projects"][0]  # type: ignore[index]
    measurement[field] = bad_value

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(item for item in gate.findings if item.check_id.startswith(finding_prefix))
    assert finding.status is ProbeStatus.FAIL


def test_missing_executable_is_explicit() -> None:
    report = run_invariant_probes(installed=lambda _executable: False)

    assert report.ok is False
    assert {probe.status for probe in report.probes} == {ProbeStatus.MISSING}


def test_malformed_json_fails_closed() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )
    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, "not-json", ""),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_exit_code_and_body_must_agree() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )
    body = {
        "component": "component",
        "probe_version": 1,
        "ok": True,
        "checks": [{"id": "component.check", "status": "pass"}],
    }
    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 1, json.dumps(body), ""),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.FAIL


def test_zero_declared_probes_cannot_pass() -> None:
    report = run_invariant_probes(specs=())

    assert report.ok is False
    assert report.probes == ()


def test_duplicate_check_ids_are_malformed() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )
    body = {
        "component": "component",
        "probe_version": 1,
        "ok": True,
        "checks": [
            {"id": "component.check", "status": "pass"},
            {"id": "component.check", "status": "pass"},
        ],
    }

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, json.dumps(body), ""),
    )

    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_empty_check_id_is_malformed() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )
    body = {
        "component": "component",
        "probe_version": 1,
        "ok": True,
        "checks": [
            {"id": "", "status": "pass"},
            {"id": "component.check", "status": "pass"},
        ],
    }

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, json.dumps(body), ""),
    )

    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_component_name_must_match_probe_spec() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["component"] = "cairn"

    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED


def test_probe_cannot_supply_another_components_check() -> None:
    bodies = _passing_bodies()
    bodies["cairn"]["checks"].append(  # type: ignore[union-attr]
        {"id": "agent_notes.session_identity_resolvable", "status": "pass"}
    )

    report = _run_bodies(bodies)

    cairn = next(probe for probe in report.probes if probe.component == "cairn")
    assert cairn.status is ProbeStatus.MALFORMED


def test_required_success_status_is_exact() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"][0]["status"] = "pass"  # type: ignore[index]

    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED


@pytest.mark.parametrize(
    ("field", "bad_value", "check_id"),
    [
        ("store_fingerprint", "sha256:" + "b" * 64, "regista.target_store_bound"),
        ("project", "other-project", "regista.target_project_bound"),
        ("snapshot_id", "", "regista.observation_snapshot_bound"),
    ],
)
def test_measurement_binding_must_match_target(
    field: str, bad_value: object, check_id: str
) -> None:
    bodies = deepcopy(_passing_bodies())
    if field == "store_fingerprint":
        bodies["regista"]["checks"][0][field] = bad_value  # type: ignore[index]
    else:
        measurement = bodies["regista"]["checks"][0]["projects"][0]  # type: ignore[index]
        measurement[field] = bad_value

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(item for item in gate.findings if item.check_id == check_id)
    assert finding.status is ProbeStatus.FAIL


def test_missing_expected_binding_cannot_open_gate() -> None:
    gate = evaluate_genesis_gate(_run_bodies(_passing_bodies()))

    assert gate.ok is False


def test_gate_is_scoped_to_target_project_namespace() -> None:
    bodies = _passing_bodies()
    other = _clean_measurement()
    other["project"] = "existing-project"
    other["event_count"] = 12
    bodies["regista"]["checks"][0]["projects"].append(other)  # type: ignore[index,union-attr]

    gate = _evaluate(bodies)

    assert gate.ok is True


def test_duplicate_target_project_measurements_fail_closed() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"][0]["projects"].append(_clean_measurement())  # type: ignore[index,union-attr]

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(
        item for item in gate.findings if item.check_id == "regista.target_project_bound"
    )
    assert finding.status is ProbeStatus.FAIL


def test_undecodable_probe_output_is_a_deterministic_malformed_result() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(
            command,
            0,
            stdout=b"\xff\xfe",  # type: ignore[arg-type]
            stderr="",
        ),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED
    assert report.probes[0].detail == "probe output was not valid UTF-8"


def test_runner_decode_error_does_not_leak_the_child_bytes() -> None:
    spec = ProbeSpec(
        "component", ("component", "probe"), frozenset({"component.check"})
    )

    def runner(_command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        raise UnicodeDecodeError("utf-8", b"secret-ish bytes", 0, 1, "invalid start byte")

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=runner,
    )

    assert report.probes[0].status is ProbeStatus.MALFORMED
    assert "secret-ish" not in report.probes[0].detail
    assert report.probes[0].detail == "probe output was not valid UTF-8"


@pytest.mark.parametrize(
    "spec",
    [
        ProbeSpec("component", (), frozenset({"component.check"})),
        ProbeSpec("component", ("component", "probe"), frozenset()),
        ProbeSpec("component", ("component", "probe"), frozenset({"check"})),
        ProbeSpec("", ("component", "probe"), frozenset({"component.check"})),
    ],
)
def test_invalid_probe_specs_cannot_green(spec: ProbeSpec) -> None:
    report = run_invariant_probes(specs=(spec,))

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_unsupported_probe_exit_status_is_an_error() -> None:
    bodies = _passing_bodies()

    by_executable = {spec.command[0]: spec.component for spec in _PASSING_SPECS}

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        component = by_executable[command[0]]
        return subprocess.CompletedProcess(
            command,
            137 if component == "regista" else 0,
            stdout=json.dumps(bodies[component]),
            stderr="",
        )

    report = run_invariant_probes(
        specs=_PASSING_SPECS,
        runner=runner,
        installed=lambda _executable: True,
    )

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.ERROR
    assert "unsupported status 137" in regista.detail


def test_boolean_probe_version_is_not_an_integer_version() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["probe_version"] = True

    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body.pop("component"),
        lambda body: body.__setitem__("component", "cairn"),
        lambda body: body.pop("probe_version"),
        lambda body: body.__setitem__("probe_version", 2),
        lambda body: body["checks"][0].__setitem__("id", "foreign.check"),
        lambda body: body["checks"][0].__setitem__("id", ""),
        lambda body: body["checks"][0].__setitem__("status", "unknown"),
    ],
)
def test_child_report_contract_is_strict(
    mutation,
) -> None:  # type: ignore[no-untyped-def]
    bodies = _passing_bodies()
    mutation(bodies["regista"])
    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED
    assert report.ok is False


def test_measurement_errors_field_is_required() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"][0].pop("errors")  # type: ignore[index]

    gate = _evaluate(bodies)

    assert gate.ok is False
    finding = next(
        item
        for item in gate.findings
        if item.check_id == "regista.store_invariant_measurements"
    )
    assert finding.status is ProbeStatus.FAIL


def test_gate_rejects_a_failed_extra_check_even_when_probe_status_is_forged() -> None:
    passing = _run_bodies(_passing_bodies())
    probe = passing.probes[0]
    forged = type(probe)(
        component=probe.component,
        status=ProbeStatus.PASS,
        checks=(*probe.checks, {"id": "regista.extra", "status": "fail"}),
        detail="forged success",
    )
    report = type(passing)(ok=True, probes=(forged,))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(item.check_id == "probe.check_status" for item in gate.findings)


def test_forged_report_ok_cannot_hide_a_failed_probe() -> None:
    passing = _run_bodies(_passing_bodies())
    failed_probe = type(passing.probes[0])(
        component="cairn",
        status=ProbeStatus.FAIL,
        checks=(),
        detail="forged",
    )
    report = type(passing)(ok=True, probes=(*passing.probes[:1], failed_probe))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(item.check_id == "probe.report" for item in gate.findings)


def test_forged_non_dict_check_is_a_blocked_finding_not_a_crash() -> None:
    passing = _run_bodies(_passing_bodies())
    probe = passing.probes[0]
    forged = type(probe)(
        component=probe.component,
        status=ProbeStatus.PASS,
        checks=(*probe.checks, "not-a-dict"),  # type: ignore[arg-type]
        detail="forged success",
    )
    report = type(passing)(ok=True, probes=(forged,))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(
        item.check_id == "probe.check_contract" and "non-object" in item.detail
        for item in gate.findings
    )


@pytest.mark.parametrize("bad_status", [[1], {"value": "pass"}, 7])
def test_non_string_check_status_is_malformed_not_a_traceback(bad_status: object) -> None:
    bodies = _passing_bodies()
    bodies["regista"]["checks"][1]["status"] = bad_status  # type: ignore[index]

    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED
    assert "known status" in regista.detail
    assert report.ok is False


def test_forged_unhashable_check_status_is_a_blocked_finding_not_a_crash() -> None:
    passing = _run_bodies(_passing_bodies())
    probe = passing.probes[0]
    forged = type(probe)(
        component=probe.component,
        status=ProbeStatus.PASS,
        checks=(*probe.checks, {"id": "regista.forged", "status": [1]}),
        detail="forged success",
    )
    report = type(passing)(ok=True, probes=(forged,))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(item.check_id == "probe.check_contract" for item in gate.findings)


def test_forged_bare_actor_boundary_check_cannot_bypass_parser() -> None:
    passing = _run_bodies(_passing_bodies())
    probes = []
    for probe in passing.probes:
        checks = tuple(
            {"id": check["id"], "status": check["status"]}
            if check.get("id") == "regista.actor_boundary_signing"
            else check
            for check in probe.checks
        )
        probes.append(
            type(probe)(
                component=probe.component,
                status=probe.status,
                checks=checks,
                detail=probe.detail,
            )
        )
    report = type(passing)(ok=True, probes=tuple(probes))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    finding = next(
        item
        for item in gate.findings
        if item.check_id == "regista.actor_boundary_signing"
    )
    assert finding.status is ProbeStatus.FAIL
    assert "scoped claim" in finding.detail


def test_duplicate_component_entries_are_rejected_not_last_wins() -> None:
    passing = _run_bodies(_passing_bodies())
    incomplete = type(passing.probes[0])(
        component="regista",
        status=ProbeStatus.PASS,
        checks=(),
        detail="forged incomplete duplicate",
    )
    report = type(passing)(ok=True, probes=(incomplete, *passing.probes))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(
        item.check_id == "probe.component_contract"
        and item.status is ProbeStatus.FAIL
        and "duplicate" in item.detail
        for item in gate.findings
    )


def test_fail_owner_probe_detail_never_claims_a_pass() -> None:
    bodies = _passing_bodies()
    # The probe self-reports failure while every individual check passes.
    bodies["regista"]["ok"] = False

    gate = _evaluate(bodies)

    assert gate.ok is False
    assert any(item.check_id == "probe.report" for item in gate.findings)
    regista_findings = [
        item
        for item in gate.findings
        if item.check_id in GENESIS_REQUIRED_CHECKS
        and GENESIS_REQUIRED_CHECK_OWNERS[item.check_id] == "regista"
    ]
    assert regista_findings
    for finding in regista_findings:
        assert finding.status is ProbeStatus.FAIL
        assert "passed" not in finding.detail


def test_empty_probe_report_cannot_open_gate() -> None:
    empty = evaluate_genesis_gate(
        type(_run_bodies(_passing_bodies()))(ok=True, probes=()),
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert empty.ok is False
    assert any(item.check_id == "probe.report" for item in empty.findings)


def test_forged_unhashable_component_is_a_blocked_finding_not_a_crash() -> None:
    """Ceremony B1 (deepseek-v4-flash): the duplicate-detection code itself
    hashed probe.component unguarded — a forged report carrying a list/dict
    component crashed the public evaluator with the exact TypeError class
    WI-076 eliminates for check statuses. Now: named finding, gate blocked."""
    passing = _run_bodies(_passing_bodies())
    probe = passing.probes[0]
    forged = type(probe)(
        component=["regista"],
        status=ProbeStatus.PASS,
        checks=probe.checks,
        detail="forged unhashable component",
    )
    report = type(passing)(ok=True, probes=(forged, *passing.probes))

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    assert any(
        item.check_id == "probe.component_contract"
        and "non-empty string" in item.detail
        for item in gate.findings
    )


@pytest.mark.parametrize("placement", ["before", "after", "triple"])
def test_duplicate_component_is_rejected_in_every_ordering(placement: str) -> None:
    """Ceremony N4: pin the orderings beyond the original bypass shape —
    duplicate after the complete entry, and triple duplicates (the second
    occurrence never enters seen_components; correctness relies on the first
    remaining there)."""
    passing = _run_bodies(_passing_bodies())
    incomplete = type(passing.probes[0])(
        component="regista",
        status=ProbeStatus.PASS,
        checks=(),
        detail="forged incomplete duplicate",
    )
    if placement == "before":
        probes = (incomplete, *passing.probes)
    elif placement == "after":
        probes = (*passing.probes, incomplete)
    else:
        probes = (incomplete, *passing.probes, incomplete)
    report = type(passing)(ok=True, probes=probes)

    gate = evaluate_genesis_gate(
        report,
        expected_store_fingerprint=_STORE_FINGERPRINT,
        expected_project=_PROJECT,
    )

    assert gate.ok is False
    duplicates = [
        item
        for item in gate.findings
        if item.check_id == "probe.component_contract" and "duplicate" in item.detail
    ]
    expected = 2 if placement == "triple" else 1
    assert len(duplicates) == expected
