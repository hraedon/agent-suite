from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest

from agent_suite.genesis_gate import (
    GENESIS_REQUIRED_CHECKS,
    PROBE_SPECS,
    ProbeSpec,
    ProbeStatus,
    evaluate_genesis_gate,
    run_invariant_probes,
)

_PASSING_SPECS = (
    *PROBE_SPECS,
    ProbeSpec(
        "agent-notes",
        ("agent-notes", "invariants", "probe", "--json"),
        frozenset({"agent_notes.session_identity_resolvable"}),
    ),
)


def _clean_measurement() -> dict[str, object]:
    return {
        "project": "throwaway",
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
                    "projects": [_clean_measurement()],
                    "errors": [],
                },
                {"id": "regista.load_bearing_fields_refused", "status": "pass"},
                {"id": "regista.closed_lineage_registry", "status": "pass"},
                {"id": "regista.first_write_admission", "status": "pass"},
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


def test_throwaway_pass_fixture_opens_gate() -> None:
    probes = _run_bodies(_passing_bodies())
    gate = evaluate_genesis_gate(probes)

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

    gate = evaluate_genesis_gate(_run_bodies(bodies))

    assert gate.ok is False
    finding = next(item for item in gate.findings if item.check_id == check_id)
    assert finding.status is ProbeStatus.FAIL


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
        ("event_count", 0.0, "regista.store_empty"),
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

    gate = evaluate_genesis_gate(_run_bodies(bodies))

    assert gate.ok is False
    finding = next(item for item in gate.findings if item.check_id.startswith(finding_prefix))
    assert finding.status is ProbeStatus.FAIL


def test_missing_executable_is_explicit() -> None:
    report = run_invariant_probes(installed=lambda _executable: False)

    assert report.ok is False
    assert {probe.status for probe in report.probes} == {ProbeStatus.MISSING}


def test_malformed_json_fails_closed() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"component.check"}))
    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, "not-json", ""),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_undecodable_probe_output_is_a_deterministic_malformed_result() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"component.check"}))

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(
            command,
            0,
            stdout=b"\xff\xfe",
            stderr="",
        ),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED
    assert report.probes[0].detail == "probe output was not valid UTF-8"


def test_runner_decode_error_does_not_leak_the_child_bytes() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"component.check"}))

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


def test_exit_code_and_body_must_agree() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"component.check"}))
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


@pytest.mark.parametrize(
    "spec",
    [
        ProbeSpec("component", (), frozenset({"component.check"})),
        ProbeSpec("component", ("component", "probe"), frozenset()),
        ProbeSpec("component", ("component", "probe"), frozenset({"check"})),
    ],
)
def test_invalid_probe_specs_cannot_green(spec: ProbeSpec) -> None:
    report = run_invariant_probes(specs=(spec,))

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_duplicate_check_ids_are_malformed() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"component.check"}))
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


def test_boolean_probe_version_is_not_an_integer_version() -> None:
    bodies = _passing_bodies()
    bodies["regista"]["probe_version"] = True

    report = _run_bodies(bodies)

    regista = next(probe for probe in report.probes if probe.component == "regista")
    assert regista.status is ProbeStatus.MALFORMED


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

    gate = evaluate_genesis_gate(report)

    assert gate.ok is False
    assert any(item.check_id == "probe.check_status" for item in gate.findings)


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

    gate = evaluate_genesis_gate(_run_bodies(bodies))

    assert gate.ok is False
    finding = next(
        item
        for item in gate.findings
        if item.check_id == "regista.store_invariant_measurements"
    )
    assert finding.status is ProbeStatus.FAIL


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("declared_lineage_event_count", 1),
        ("lineage_coverage", {"numerator": 0, "denominator": 1}),
        ("distinct_lineage_tokens", ["glm"]),
        ("model_observation_status_counts", {"observed": 1}),
    ],
)
def test_empty_store_requires_all_measurement_fields_to_be_empty(
    field: str,
    bad_value: object,
) -> None:
    bodies = deepcopy(_passing_bodies())
    measurement = bodies["regista"]["checks"][0]["projects"][0]  # type: ignore[index]
    measurement[field] = bad_value

    gate = evaluate_genesis_gate(_run_bodies(bodies))

    assert gate.ok is False
    assert any(
        finding.status is ProbeStatus.FAIL
        and finding.check_id.startswith("regista.")
        for finding in gate.findings
    )


def test_gate_rejects_check_id_copied_between_component_reports() -> None:
    bodies = _passing_bodies()
    bodies["cairn"]["checks"].append(  # type: ignore[union-attr]
        {"id": "regista.first_write_admission", "status": "pass"}
    )

    gate = evaluate_genesis_gate(_run_bodies(bodies))

    assert gate.ok is False
    assert any(item.check_id == "probe.check_contract" for item in gate.findings)


def test_gate_rejects_a_non_object_check_without_crashing() -> None:
    probe = type(_run_bodies(_passing_bodies()).probes[0])(
        component="regista",
        status=ProbeStatus.PASS,
        checks=(object(),),  # type: ignore[arg-type]
        detail="forged",
    )
    report = type(_run_bodies(_passing_bodies()))(ok=True, probes=(probe,))

    gate = evaluate_genesis_gate(report)

    assert gate.ok is False
    assert any(item.check_id == "probe.check_contract" for item in gate.findings)


def test_gate_does_not_trust_a_forged_aggregate_ok_flag() -> None:
    probe = _run_bodies(_passing_bodies()).probes[0]
    forged = type(probe)(
        component=probe.component,
        status=ProbeStatus.FAIL,
        checks=probe.checks,
        detail="forged failure",
    )
    report = type(_run_bodies(_passing_bodies()))(ok=True, probes=(forged,))

    assert evaluate_genesis_gate(report).ok is False
