"""Read-only component probes and the pre-genesis admission verdict.

The component CLIs own the measurements.  This module only validates their
versioned report shape and composes the measurements into a fail-closed gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, assert_never


class ProbeStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"
    MALFORMED = "malformed"
    ERROR = "error"


PROBE_REPORT_VERSION = 1
GENESIS_GATE_REPORT_VERSION = 1
_PROBE_CHECK_STATUSES = frozenset({"pass", "measured", "fail"})


@dataclass(frozen=True)
class ProbeSpec:
    component: str
    command: tuple[str, ...]
    required_checks: frozenset[str]


@dataclass(frozen=True)
class ProbeResult:
    component: str
    status: ProbeStatus
    checks: tuple[dict[str, Any], ...]
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is ProbeStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status.value,
            "ok": self.ok,
            "detail": self.detail,
            "checks": list(self.checks),
        }


@dataclass(frozen=True)
class InvariantProbeReport:
    ok: bool
    probes: tuple[ProbeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": PROBE_REPORT_VERSION,
            "kind": "invariant_probes",
            "ok": self.ok,
            "probes": [probe.to_dict() for probe in self.probes],
        }


@dataclass(frozen=True)
class GateFinding:
    check_id: str
    status: ProbeStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GenesisGateReport:
    ok: bool
    findings: tuple[GateFinding, ...]
    probes: InvariantProbeReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": GENESIS_GATE_REPORT_VERSION,
            "kind": "genesis_gate",
            "ok": self.ok,
            "epoch_may_open": self.ok,
            "findings": [finding.to_dict() for finding in self.findings],
            "probes": self.probes.to_dict(),
        }


class Runner(Protocol):
    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    def __call__(self, executable: str) -> bool: ...


PROBE_SPECS: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        component="regista",
        command=("regista", "invariants", "probe", "--json"),
        required_checks=frozenset(
            {
                "regista.store_invariant_measurements",
                "regista.closed_lineage_registry",
            }
        ),
    ),
    ProbeSpec(
        component="cairn",
        command=("cairn", "invariants", "probe", "--json"),
        required_checks=frozenset(
            {
                "cairn.runtime_model_observed",
                "cairn.unavailable_model_named",
                "cairn.observation_failure_nonblocking",
            }
        ),
    ),
)


GENESIS_REQUIRED_CHECKS: frozenset[str] = frozenset(
    {
        "regista.load_bearing_fields_refused",
        "regista.closed_lineage_registry",
        "regista.first_write_admission",
        "cairn.runtime_model_observed",
        "cairn.unavailable_model_named",
        "cairn.observation_failure_nonblocking",
        "agent_notes.session_identity_resolvable",
    }
)


def _default_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _default_installed(executable: str) -> bool:
    return shutil.which(executable) is not None


def _status_detail(status: ProbeStatus) -> str:
    match status:
        case ProbeStatus.PASS:
            return "probe executed and declared complete check coverage"
        case ProbeStatus.FAIL:
            return "probe reported a failed invariant"
        case ProbeStatus.MISSING:
            return "probe executable is not installed"
        case ProbeStatus.MALFORMED:
            return "probe result did not satisfy the JSON contract"
        case ProbeStatus.ERROR:
            return "probe process failed"
        case _ as unreachable:
            assert_never(unreachable)


def _component_namespace(component: str) -> str:
    """Return the check-ID namespace used by *component* reports."""
    return component.replace("-", "_")


def _parse_probe_result(
    spec: ProbeSpec,
    completed: subprocess.CompletedProcess[str],
) -> ProbeResult:
    output = completed.stdout
    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8")
        except UnicodeDecodeError:
            return ProbeResult(
                spec.component,
                ProbeStatus.MALFORMED,
                (),
                "probe output was not valid UTF-8",
            )
    if not isinstance(output, str):
        output = None
    try:
        body = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
        )
    if not isinstance(body, dict) or not isinstance(body.get("ok"), bool):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
        )
    if body.get("component") != spec.component:
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            f"probe component must be {spec.component!r}",
        )
    if (
        type(body.get("probe_version")) is not int
        or body.get("probe_version") != PROBE_REPORT_VERSION
    ):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            f"unsupported or missing probe_version (expected {PROBE_REPORT_VERSION})",
        )
    raw_checks = body.get("checks")
    if not isinstance(raw_checks, list) or not all(isinstance(check, dict) for check in raw_checks):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
        )
    checks = tuple(raw_checks)
    namespace = f"{_component_namespace(spec.component)}."
    check_ids: set[str] = set()
    for check in checks:
        check_id = check.get("id")
        status = check.get("status")
        if (
            not isinstance(check_id, str)
            or not check_id
            or check_id != check_id.strip()
            or not check_id.startswith(namespace)
            or not isinstance(status, str)
            or status not in _PROBE_CHECK_STATUSES
        ):
            return ProbeResult(
                spec.component,
                ProbeStatus.MALFORMED,
                checks,
                "probe checks must have unique namespaced IDs and known statuses",
            )
        check_ids.add(check_id)
    if len(check_ids) != len(checks):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            checks,
            "probe check IDs must be unique non-empty strings",
        )
    if not spec.required_checks.issubset(check_ids):
        missing = sorted(spec.required_checks - check_ids)
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            checks,
            f"probe omitted required check IDs: {', '.join(missing)}",
        )
    if completed.returncode not in (0, 1):
        return ProbeResult(
            spec.component,
            ProbeStatus.ERROR,
            checks,
            f"probe exited with unsupported status {completed.returncode}",
        )
    failed_ids = [
        str(check["id"])
        for check in checks
        if check.get("status") not in {"pass", "measured"}
    ]
    checks_pass = not failed_ids
    process_agrees = (completed.returncode == 0) == body["ok"]
    status = ProbeStatus.PASS if body["ok"] and checks_pass and process_agrees else ProbeStatus.FAIL
    if status is ProbeStatus.FAIL and failed_ids:
        detail = f"failed checks: {', '.join(failed_ids)}"
    elif status is ProbeStatus.FAIL and not body["ok"]:
        detail = "probe reported ok=false"
    elif status is ProbeStatus.FAIL:
        detail = "probe exit code disagreed with its ok field"
    else:
        detail = _status_detail(status)
    return ProbeResult(spec.component, status, checks, detail)


def run_invariant_probes(
    *,
    specs: Sequence[ProbeSpec] = PROBE_SPECS,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> InvariantProbeReport:
    results: list[ProbeResult] = []
    for spec in specs:
        if not isinstance(spec.component, str) or not spec.component.strip():
            results.append(
                ProbeResult(
                    str(spec.component),
                    ProbeStatus.MALFORMED,
                    (),
                    "probe specification must declare a non-empty component",
                )
            )
            continue
        namespace = f"{_component_namespace(spec.component)}."
        if (
            not spec.command
            or not all(isinstance(part, str) and part for part in spec.command)
            or not spec.required_checks
            or any(
                not isinstance(check_id, str)
                or not check_id.startswith(namespace)
                or check_id == namespace
                for check_id in spec.required_checks
            )
        ):
            results.append(
                ProbeResult(
                    spec.component,
                    ProbeStatus.MALFORMED,
                    (),
                    "probe specification must declare a command and namespaced checks",
                )
            )
            continue
        if not installed(spec.command[0]):
            results.append(
                ProbeResult(
                    spec.component,
                    ProbeStatus.MISSING,
                    (),
                    _status_detail(ProbeStatus.MISSING),
                )
            )
            continue
        try:
            completed = runner(spec.command)
        except UnicodeDecodeError:
            results.append(
                ProbeResult(
                    spec.component,
                    ProbeStatus.MALFORMED,
                    (),
                    "probe output was not valid UTF-8",
                )
            )
            continue
        except (OSError, subprocess.TimeoutExpired):
            results.append(
                ProbeResult(
                    spec.component,
                    ProbeStatus.ERROR,
                    (),
                    _status_detail(ProbeStatus.ERROR),
                )
            )
            continue
        results.append(_parse_probe_result(spec, completed))
    return InvariantProbeReport(
        ok=bool(results) and all(result.ok for result in results),
        probes=tuple(results),
    )


def _checks_by_id(report: InvariantProbeReport) -> dict[str, dict[str, Any]]:
    return {
        check["id"]: check
        for probe in report.probes
        for check in probe.checks
        if isinstance(check, dict) and isinstance(check.get("id"), str)
    }


def _probe_contract_findings(report: InvariantProbeReport) -> list[GateFinding]:
    """Reject forged, duplicated, or otherwise unscoped check identifiers.

    Normal subprocess results are checked by :func:`_parse_probe_result`, but
    the evaluator is also a public pure function.  Rechecking ownership here
    prevents a caller from satisfying (for example) a ``regista.*`` gate with
    a check copied into an unrelated component's result.
    """
    findings: list[GateFinding] = []
    seen: dict[str, str] = {}
    for probe in report.probes:
        namespace = f"{_component_namespace(probe.component)}."
        for check in probe.checks:
            if not isinstance(check, dict):
                findings.append(
                    GateFinding(
                        "probe.check_contract",
                        ProbeStatus.FAIL,
                        f"{probe.component} returned a non-object check",
                    )
                )
                continue
            check_id = check.get("id")
            if (
                not isinstance(check_id, str)
                or not check_id
                or check_id != check_id.strip()
                or not check_id.startswith(namespace)
                or check.get("status") not in _PROBE_CHECK_STATUSES
            ):
                findings.append(
                    GateFinding(
                        "probe.check_contract",
                        ProbeStatus.FAIL,
                        f"{probe.component} returned an invalid or foreign check ID",
                    )
                )
                continue
            if check.get("status") == "fail":
                findings.append(
                    GateFinding(
                        "probe.check_status",
                        ProbeStatus.FAIL,
                        f"{probe.component} returned a failed check {check_id!r}",
                    )
                )
            previous = seen.get(check_id)
            if previous is not None:
                findings.append(
                    GateFinding(
                        "probe.check_contract",
                        ProbeStatus.FAIL,
                        f"check ID {check_id!r} was returned by both {previous} and "
                        f"{probe.component}",
                    )
                )
            else:
                seen[check_id] = probe.component
    return findings


def _measurement_findings(check: Mapping[str, Any] | None) -> list[GateFinding]:
    if check is None:
        return [
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "store invariant measurements are absent",
            )
        ]
    errors = check.get("errors")
    if (
        check.get("status") != "measured"
        or not isinstance(errors, list)
        or not all(isinstance(error, dict) for error in errors)
        or errors
    ):
        return [
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "one or more project measurements failed",
            )
        ]
    projects = check.get("projects")
    if not isinstance(projects, list) or not projects:
        return [
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "no project measurements were returned",
            )
        ]
    findings: list[GateFinding] = []
    project_names: set[str] = set()

    def exact_nonnegative_int(value: object) -> bool:
        return type(value) is int and value >= 0

    predicates: tuple[tuple[str, Callable[[Mapping[str, Any]], bool], str], ...] = (
        (
            "store_empty",
            lambda row: type(row.get("event_count")) is int and row["event_count"] == 0,
            "event_count must be the integer zero",
        ),
        (
            "lineage_counts_empty",
            lambda row: type(row.get("declared_lineage_event_count")) is int
            and row["declared_lineage_event_count"] == 0
            and isinstance(row.get("lineage_coverage"), dict)
            and type(row["lineage_coverage"].get("numerator")) is int
            and type(row["lineage_coverage"].get("denominator")) is int
            and row["lineage_coverage"]["numerator"] == 0
            and row["lineage_coverage"]["denominator"] == 0,
            "lineage coverage must be the exact empty-store shape",
        ),
        (
            "lineage_tokens_empty",
            lambda row: isinstance(row.get("distinct_lineage_tokens"), list)
            and row["distinct_lineage_tokens"] == [],
            "distinct lineage tokens must be empty",
        ),
        (
            "lineage_tokens_resolvable",
            lambda row: isinstance(row.get("unresolvable_lineage_tokens"), list)
            and row["unresolvable_lineage_tokens"] == []
            and exact_nonnegative_int(row.get("unresolvable_lineage_value_count"))
            and row["unresolvable_lineage_value_count"] == 0,
            "unresolvable lineage values exist",
        ),
        (
            "lineage_unambiguous",
            lambda row: exact_nonnegative_int(row.get("ambiguous_lineage_event_count"))
            and row["ambiguous_lineage_event_count"] == 0,
            "events carry conflicting canonical lineages",
        ),
        (
            "asymmetric_only",
            lambda row: isinstance(row.get("scheme_counts"), dict)
            and row["scheme_counts"] == {},
            "scheme_counts must be an empty object before genesis",
        ),
        (
            "model_observations_empty",
            lambda row: isinstance(row.get("model_observation_status_counts"), dict)
            and row["model_observation_status_counts"] == {},
            "model-observation statuses must be empty before genesis",
        ),
        (
            "authors_declared",
            lambda row: exact_nonnegative_int(
                row.get("undeclared_agent_author_event_count")
            )
            and row["undeclared_agent_author_event_count"] == 0,
            "undeclared agent authors exist",
        ),
    )
    for project in projects:
        if (
            not isinstance(project, dict)
            or not isinstance(project.get("project"), str)
            or not project["project"].strip()
        ):
            findings.append(
                GateFinding(
                    "regista.store_invariant_measurements",
                    ProbeStatus.FAIL,
                    "project measurement is malformed",
                )
            )
            continue
        project_name = project["project"]
        if project_name in project_names:
            findings.append(
                GateFinding(
                    "regista.store_invariant_measurements",
                    ProbeStatus.FAIL,
                    f"project measurement is duplicated: {project_name}",
                )
            )
            continue
        project_names.add(project_name)
        for suffix, predicate, failure in predicates:
            passed = predicate(project)
            findings.append(
                GateFinding(
                    f"regista.{suffix}:{project_name}",
                    ProbeStatus.PASS if passed else ProbeStatus.FAIL,
                    "pass condition satisfied" if passed else failure,
                )
            )
    return findings


def evaluate_genesis_gate(probes: InvariantProbeReport) -> GenesisGateReport:
    checks = _checks_by_id(probes)
    findings = _probe_contract_findings(probes)
    findings.extend(_measurement_findings(checks.get("regista.store_invariant_measurements")))
    for check_id in sorted(GENESIS_REQUIRED_CHECKS):
        check = checks.get(check_id)
        passed = check is not None and check.get("status") == "pass"
        if check is None:
            detail = "required behavioral probe is absent"
        elif passed:
            detail = "behavioral probe passed"
        else:
            detail = "required behavioral probe reported failure"
        findings.append(
            GateFinding(
                check_id,
                ProbeStatus.PASS if passed else ProbeStatus.FAIL,
                detail,
            )
        )
    probe_health = bool(probes.probes) and probes.ok and all(probe.ok for probe in probes.probes)
    if not probe_health:
        findings.append(
            GateFinding(
                "probe.report",
                ProbeStatus.FAIL,
                "one or more component probes did not complete successfully",
            )
        )
    ok = probe_health and all(finding.status is ProbeStatus.PASS for finding in findings)
    return GenesisGateReport(ok=ok, findings=tuple(findings), probes=probes)


def format_invariant_probes(report: InvariantProbeReport) -> str:
    lines = ["Invariant probes:"]
    for probe in report.probes:
        lines.append(f"  [{probe.status.value.upper()}] {probe.component}: {probe.detail}")
    return "\n".join(lines)


def format_genesis_gate(report: GenesisGateReport) -> str:
    state = "PASS" if report.ok else "BLOCKED"
    lines = [f"Genesis gate: {state}"]
    for finding in report.findings:
        lines.append(f"  [{finding.status.value.upper()}] {finding.check_id}: {finding.detail}")
    return "\n".join(lines)
