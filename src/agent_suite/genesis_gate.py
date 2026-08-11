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
            "report_version": 1,
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
            "report_version": 1,
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


def _parse_probe_result(
    spec: ProbeSpec,
    completed: subprocess.CompletedProcess[str],
) -> ProbeResult:
    try:
        body = json.loads(completed.stdout)
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
    raw_checks = body.get("checks")
    if not isinstance(raw_checks, list) or not all(isinstance(check, dict) for check in raw_checks):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
        )
    checks = tuple(raw_checks)
    check_ids = {
        check.get("id") for check in checks if isinstance(check.get("id"), str)
    }
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
    failed_ids = [
        str(check["id"])
        for check in checks
        if check.get("status") not in {"pass", "measured"}
    ]
    checks_pass = not failed_ids
    process_agrees = (completed.returncode == 0) == body["ok"]
    status = ProbeStatus.PASS if body["ok"] and checks_pass and process_agrees else ProbeStatus.FAIL
    detail = (
        f"failed checks: {', '.join(failed_ids)}"
        if status is ProbeStatus.FAIL and failed_ids
        else _status_detail(status)
    )
    return ProbeResult(spec.component, status, checks, detail)


def run_invariant_probes(
    *,
    specs: Sequence[ProbeSpec] = PROBE_SPECS,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> InvariantProbeReport:
    results: list[ProbeResult] = []
    for spec in specs:
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
        if isinstance(check.get("id"), str)
    }


def _measurement_findings(check: Mapping[str, Any] | None) -> list[GateFinding]:
    if check is None:
        return [
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "store invariant measurements are absent",
            )
        ]
    if check.get("status") != "measured" or check.get("errors"):
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

    def exact_nonnegative_int(value: object) -> bool:
        return type(value) is int and value >= 0

    predicates: tuple[tuple[str, Callable[[Mapping[str, Any]], bool], str], ...] = (
        (
            "store_empty",
            lambda row: type(row.get("event_count")) is int and row["event_count"] == 0,
            "event_count must be the integer zero",
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
            "authors_declared",
            lambda row: exact_nonnegative_int(
                row.get("undeclared_agent_author_event_count")
            )
            and row["undeclared_agent_author_event_count"] == 0,
            "undeclared agent authors exist",
        ),
    )
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("project"), str):
            findings.append(
                GateFinding(
                    "regista.store_invariant_measurements",
                    ProbeStatus.FAIL,
                    "project measurement is malformed",
                )
            )
            continue
        for suffix, predicate, failure in predicates:
            passed = predicate(project)
            findings.append(
                GateFinding(
                    f"regista.{suffix}:{project['project']}",
                    ProbeStatus.PASS if passed else ProbeStatus.FAIL,
                    "pass condition satisfied" if passed else failure,
                )
            )
    return findings


def evaluate_genesis_gate(probes: InvariantProbeReport) -> GenesisGateReport:
    checks = _checks_by_id(probes)
    findings = _measurement_findings(checks.get("regista.store_invariant_measurements"))
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
    ok = probes.ok and all(finding.status is ProbeStatus.PASS for finding in findings)
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
