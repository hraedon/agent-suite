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
    #: Whether ``schedule install`` must verify (parser-only) that the
    #: component CLI exposes ``invariants probe`` before installing the probe
    #: schedule. False only while a component's probe contribution is itself a
    #: named, tracked gate blocker: the schedule must remain installable so
    #: the implemented probes are measured continuously, and the runtime probe
    #: honestly reports the missing component on every scheduled run.
    preflight_capability: bool = True


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
    target_store_fingerprint: str | None = None
    reported_store_fingerprint: str | None = None
    target_project: str | None = None
    observation_snapshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": GENESIS_GATE_REPORT_VERSION,
            "kind": "genesis_gate",
            "ok": self.ok,
            "epoch_may_open": self.ok,
            "binding": {
                "expected_store_fingerprint": self.target_store_fingerprint,
                "reported_store_fingerprint": self.reported_store_fingerprint,
                "project": self.target_project,
                "observation_snapshot": self.observation_snapshot,
            },
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
                "regista.load_bearing_fields_refused",
                "regista.closed_lineage_registry",
                "regista.first_write_admission",
                "regista.actor_boundary_signing",
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
    ProbeSpec(
        component="agent-notes",
        command=("agent-notes", "invariants", "probe", "--json"),
        required_checks=frozenset({"agent_notes.session_identity_resolvable"}),
        # The agent-notes session-identity probe is a named gate blocker that
        # has not shipped; flip this to True in the change that ships it.
        preflight_capability=False,
    ),
)


GENESIS_REQUIRED_CHECK_OWNERS: Mapping[str, str] = {
    "regista.load_bearing_fields_refused": "regista",
    "regista.closed_lineage_registry": "regista",
    "regista.first_write_admission": "regista",
    "regista.actor_boundary_signing": "regista",
    "cairn.runtime_model_observed": "cairn",
    "cairn.unavailable_model_named": "cairn",
    "cairn.observation_failure_nonblocking": "cairn",
    "agent_notes.session_identity_resolvable": "agent-notes",
}
GENESIS_REQUIRED_CHECKS: frozenset[str] = frozenset(GENESIS_REQUIRED_CHECK_OWNERS)


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
    output: object = completed.stdout
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
        body = json.loads(output)  # type: ignore[arg-type]
    except (TypeError, json.JSONDecodeError):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
        )
    if (
        not isinstance(body, dict)
        or body.get("component") != spec.component
        or not isinstance(body.get("ok"), bool)
    ):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            (),
            _status_detail(ProbeStatus.MALFORMED),
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
    if any(check.get("status") not in _PROBE_CHECK_STATUSES for check in checks):
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            checks,
            "probe checks must use a known status (pass, measured, fail)",
        )
    check_ids = {
        check.get("id")
        for check in checks
        if isinstance(check.get("id"), str) and bool(check["id"].strip())
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
    component_prefix = spec.component.replace("-", "_") + "."
    foreign = sorted(
        check_id for check_id in check_ids if not check_id.startswith(component_prefix)
    )
    if foreign:
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            checks,
            f"probe emitted checks owned by another component: {', '.join(foreign)}",
        )
    required_statuses = {
        check_id: "measured" if check_id == "regista.store_invariant_measurements" else "pass"
        for check_id in spec.required_checks
    }
    by_id = {str(check["id"]): check for check in checks}
    wrong_status = sorted(
        check_id
        for check_id, expected in required_statuses.items()
        if by_id[check_id].get("status") != expected
    )
    if body["ok"] and wrong_status:
        return ProbeResult(
            spec.component,
            ProbeStatus.MALFORMED,
            checks,
            f"probe required checks used the wrong success status: {', '.join(wrong_status)}",
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
        namespace = spec.component.replace("-", "_") + "."
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
        except (OSError, subprocess.SubprocessError, UnicodeError):
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


def _checks_by_component(
    report: InvariantProbeReport,
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        probe.component: {
            check["id"]: check
            for check in probe.checks
            if isinstance(check, dict) and isinstance(check.get("id"), str)
        }
        for probe in report.probes
    }


def _probe_contract_findings(report: InvariantProbeReport) -> list[GateFinding]:
    """Reject forged, duplicated, or otherwise unscoped check identifiers.

    Normal subprocess results are checked by :func:`_parse_probe_result`, but
    the evaluator is also a public pure function.  Rechecking ownership here
    prevents a caller from satisfying (for example) a ``regista.*`` gate with
    a check copied into an unrelated component's result, and from hiding a
    failed check behind a hand-built passing ``ProbeResult``.
    """
    findings: list[GateFinding] = []
    seen: dict[str, str] = {}
    for probe in report.probes:
        namespace = probe.component.replace("-", "_") + "."
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


def _measurement_findings(
    check: Mapping[str, Any] | None,
    *,
    expected_store_fingerprint: str | None,
    expected_project: str | None,
) -> tuple[list[GateFinding], str | None]:
    if check is None:
        return ([
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "store invariant measurements are absent",
            )
        ], None)
    errors = check.get("errors")
    if (
        check.get("status") != "measured"
        or not isinstance(errors, list)
        or not all(isinstance(error, dict) for error in errors)
        or errors
    ):
        return ([
            GateFinding(
                "regista.store_invariant_measurements",
                ProbeStatus.FAIL,
                "one or more project measurements failed",
            )
        ], None)
    binding_findings: list[GateFinding] = []
    reported_store = check.get("store_fingerprint")
    store_bound = (
        expected_store_fingerprint is not None
        and isinstance(reported_store, str)
        and reported_store == expected_store_fingerprint
    )
    binding_findings.append(
        GateFinding(
            "regista.target_store_bound",
            ProbeStatus.PASS if store_bound else ProbeStatus.FAIL,
            "store fingerprint matches configured REGISTA_DSN"
            if store_bound
            else "store fingerprint is absent, unresolvable, or does not match REGISTA_DSN",
        )
    )
    projects = check.get("projects")
    if not isinstance(projects, list) or not projects:
        return (
            [
                *binding_findings,
                GateFinding(
                    "regista.store_invariant_measurements",
                    ProbeStatus.FAIL,
                    "no project measurements were returned",
                ),
            ],
            None,
        )
    matching_projects = [
        project
        for project in projects
        if isinstance(project, dict) and project.get("project") == expected_project
    ]
    project_bound = expected_project is not None and len(matching_projects) == 1
    binding_findings.append(
        GateFinding(
            "regista.target_project_bound",
            ProbeStatus.PASS if project_bound else ProbeStatus.FAIL,
            "project measurement matches configured REGISTA_PROJECT"
            if project_bound
            else "configured REGISTA_PROJECT is absent or duplicated in measurements",
        )
    )
    if not project_bound:
        return binding_findings, None
    project = matching_projects[0]
    snapshot = project.get("snapshot_id")
    snapshot_bound = isinstance(snapshot, str) and bool(snapshot.strip())
    binding_findings.append(
        GateFinding(
            "regista.observation_snapshot_bound",
            ProbeStatus.PASS if snapshot_bound else ProbeStatus.FAIL,
            "measurement carries a non-empty observation snapshot"
            if snapshot_bound
            else "project measurement does not identify its observation snapshot",
        )
    )
    findings: list[GateFinding] = binding_findings

    def exact_nonnegative_int(value: object) -> bool:
        return type(value) is int and value >= 0

    predicates: tuple[tuple[str, Callable[[Mapping[str, Any]], bool], str], ...] = (
        (
            "store_empty",
            lambda row: type(row.get("event_count")) is int and row["event_count"] == 0,
            "event_count must be the integer zero",
        ),
        (
            "lineage_population_empty",
            lambda row: exact_nonnegative_int(row.get("declared_lineage_event_count"))
            and row["declared_lineage_event_count"] == 0
            and row.get("lineage_coverage") == {"numerator": 0, "denominator": 0}
            and row.get("distinct_lineage_tokens") == [],
            "lineage measurements must describe an empty pre-genesis population",
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
        (
            "model_observation_population_empty",
            lambda row: row.get("model_observation_status_counts") == {},
            "model observation measurements must be empty before genesis",
        ),
    )
    for suffix, predicate, failure in predicates:
        passed = predicate(project)
        findings.append(
            GateFinding(
                f"regista.{suffix}:{project['project']}",
                ProbeStatus.PASS if passed else ProbeStatus.FAIL,
                "pass condition satisfied" if passed else failure,
            )
        )
    return findings, snapshot if snapshot_bound else None


def evaluate_genesis_gate(
    probes: InvariantProbeReport,
    *,
    expected_store_fingerprint: str | None = None,
    expected_project: str | None = None,
) -> GenesisGateReport:
    checks = _checks_by_component(probes)
    probes_by_component = {probe.component: probe for probe in probes.probes}
    regista_checks = checks.get("regista", {})
    measurement_check = regista_checks.get("regista.store_invariant_measurements")
    findings = _probe_contract_findings(probes)
    measurement_findings, snapshot = _measurement_findings(
        measurement_check,
        expected_store_fingerprint=expected_store_fingerprint,
        expected_project=expected_project,
    )
    findings.extend(measurement_findings)
    for check_id in sorted(GENESIS_REQUIRED_CHECKS):
        owner = GENESIS_REQUIRED_CHECK_OWNERS[check_id]
        check = checks.get(owner, {}).get(check_id)
        owner_probe = probes_by_component.get(owner)
        owner_contract_valid = owner_probe is not None and owner_probe.status in {
            ProbeStatus.PASS,
            ProbeStatus.FAIL,
        }
        passed = owner_contract_valid and check is not None and check.get("status") == "pass"
        if check is None:
            detail = f"required behavioral probe is absent from {owner}"
        elif not owner_contract_valid:
            detail = f"{owner} probe did not pass contract validation"
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
    return GenesisGateReport(
        ok=ok,
        findings=tuple(findings),
        probes=probes,
        target_store_fingerprint=expected_store_fingerprint,
        reported_store_fingerprint=(
            measurement_check.get("store_fingerprint")
            if isinstance(measurement_check, dict)
            and isinstance(measurement_check.get("store_fingerprint"), str)
            else None
        ),
        target_project=expected_project,
        observation_snapshot=snapshot,
    )


def format_invariant_probes(report: InvariantProbeReport) -> str:
    lines = ["Invariant probes:"]
    for probe in report.probes:
        lines.append(f"  [{probe.status.value.upper()}] {probe.component}: {probe.detail}")
    return "\n".join(lines)


def format_genesis_gate(report: GenesisGateReport) -> str:
    state = "PASS" if report.ok else "BLOCKED"
    lines = [
        f"Genesis gate: {state}",
        "  Binding: "
        f"project={report.target_project or 'unconfigured'}, "
        f"expected_store={report.target_store_fingerprint or 'unresolved'}, "
        f"reported_store={report.reported_store_fingerprint or 'absent'}, "
        f"snapshot={report.observation_snapshot or 'absent'}",
    ]
    for finding in report.findings:
        lines.append(f"  [{finding.status.value.upper()}] {finding.check_id}: {finding.detail}")
    return "\n".join(lines)
