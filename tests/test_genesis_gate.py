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
            "ok": True,
            "checks": [
                {
                    "id": "regista.store_invariant_measurements",
                    "status": "measured",
                    "projects": [_clean_measurement()],
                },
                {"id": "regista.load_bearing_fields_refused", "status": "pass"},
                {"id": "regista.closed_lineage_registry", "status": "pass"},
                {"id": "regista.first_write_admission", "status": "pass"},
            ],
        },
        "cairn": {
            "component": "cairn",
            "ok": True,
            "checks": [
                {"id": "cairn.runtime_model_observed", "status": "pass"},
                {"id": "cairn.unavailable_model_named", "status": "pass"},
                {"id": "cairn.observation_failure_nonblocking", "status": "pass"},
            ],
        },
        "agent-notes": {
            "component": "agent-notes",
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
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"check"}))
    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, "not-json", ""),
    )

    assert report.ok is False
    assert report.probes[0].status is ProbeStatus.MALFORMED


def test_exit_code_and_body_must_agree() -> None:
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"check"}))
    body = {"ok": True, "checks": [{"id": "check", "status": "pass"}]}
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
    spec = ProbeSpec("component", ("component", "probe"), frozenset({"check"}))
    body = {
        "ok": True,
        "checks": [
            {"id": "check", "status": "pass"},
            {"id": "check", "status": "pass"},
        ],
    }

    report = run_invariant_probes(
        specs=(spec,),
        installed=lambda _executable: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, json.dumps(body), ""),
    )

    assert report.probes[0].status is ProbeStatus.MALFORMED
