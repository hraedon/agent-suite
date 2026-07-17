"""Structured component ``install-harness`` result handling.

Newer component CLIs expose the shared JSON contract. Legacy component paths
remain callable, but non-zero is always failure and structured degraded states
fail closed until an explicit suite-tier policy permits them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from agent_suite.harness import HarnessTarget


class HarnessInstallStatus(StrEnum):
    INSTALLED = "installed"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


_JSON_INSTALL_CLIS = frozenset({"agent-notes", "cairn", "acb"})


@dataclass(frozen=True)
class HarnessInstallEvaluation:
    ok: bool
    status: HarnessInstallStatus
    no_op: bool
    detail: str


def install_harness_argv(cli_name: str, target: HarnessTarget) -> tuple[str, ...]:
    """Build positional child argv, requesting structured output when supported."""

    base = (cli_name, "install-harness", target.value)
    return base + (("--json",) if cli_name in _JSON_INSTALL_CLIS else ())


def requires_structured_install_result(cli_name: str) -> bool:
    """Return whether the suite requested the component's JSON contract."""

    return cli_name in _JSON_INSTALL_CLIS


def _result_records(payload: object) -> tuple[list[dict[str, object]], str | None]:
    if isinstance(payload, list):
        if not payload:
            return [], "JSON result list is empty"
        if not all(isinstance(item, dict) for item in payload):
            return [], "JSON result list contains a non-object entry"
        return list(payload), None
    if isinstance(payload, dict):
        nested = payload.get("results")
        if nested is not None:
            if not isinstance(nested, list) or not nested:
                return [], "JSON results field must be a non-empty list"
            if not all(isinstance(item, dict) for item in nested):
                return [], "JSON results field contains a non-object entry"
            return list(nested), None
        return [payload], None
    return [], "JSON result must be an object or non-empty list of objects"


def _diagnostic(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stderr, stdout) if part.strip()]
    detail = "; ".join(parts) or "no diagnostic output"
    return detail[:2000]


def evaluate_install_harness_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    expected_tool: str,
    expected_harness: HarnessTarget,
    require_structured: bool = False,
) -> HarnessInstallEvaluation:
    """Evaluate a child result without inferring success from prose."""

    payload: object | None = None
    if stdout.strip():
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

    records, structure_error = _result_records(payload)
    statuses: list[HarnessInstallStatus] = []
    invalid_status: object | None = None
    for record in records:
        raw_status = record.get("status")
        if raw_status is None:
            continue
        try:
            statuses.append(HarnessInstallStatus(str(raw_status)))
        except ValueError:
            invalid_status = raw_status
            break

    no_op = bool(records) and all(record.get("no_op") is True for record in records)
    diagnostic = _diagnostic(stdout, stderr)

    if require_structured:
        if not stdout.strip():
            structure_error = "structured result required but stdout is empty"
        elif payload is None:
            structure_error = "structured result required but stdout is not valid JSON"
        if structure_error is not None:
            return HarnessInstallEvaluation(
                ok=False,
                status=HarnessInstallStatus.FAILED,
                no_op=False,
                detail=structure_error,
            )
        if len(records) != 1:
            return HarnessInstallEvaluation(
                ok=False,
                status=HarnessInstallStatus.FAILED,
                no_op=False,
                detail=(
                    "structured result for one concrete invocation must contain "
                    f"exactly one record, got {len(records)}"
                ),
            )
        for record in records:
            missing = [
                key
                for key in ("tool", "harness", "status", "actions", "no_op")
                if key not in record
            ]
            if missing:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=HarnessInstallStatus.FAILED,
                    no_op=False,
                    detail=f"structured result missing fields: {', '.join(missing)}",
                )
            if not isinstance(record["actions"], list):
                return HarnessInstallEvaluation(
                    ok=False,
                    status=HarnessInstallStatus.FAILED,
                    no_op=False,
                    detail="structured result actions field must be a list",
                )
            if not isinstance(record["no_op"], bool):
                return HarnessInstallEvaluation(
                    ok=False,
                    status=HarnessInstallStatus.FAILED,
                    no_op=False,
                    detail="structured result no_op field must be boolean",
                )
            tool = record["tool"]
            if not isinstance(tool, str) or tool != expected_tool:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=HarnessInstallStatus.FAILED,
                    no_op=False,
                    detail=(
                        "structured result tool mismatch: "
                        f"expected {expected_tool!r}, got {tool!r}"
                    ),
                )
            harness = record["harness"]
            if not isinstance(harness, str) or harness != expected_harness.value:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=HarnessInstallStatus.FAILED,
                    no_op=False,
                    detail=(
                        "structured result harness mismatch: "
                        f"expected {expected_harness.value!r}, got {harness!r}"
                    ),
                )

    if invalid_status is not None:
        return HarnessInstallEvaluation(
            ok=False,
            status=HarnessInstallStatus.FAILED,
            no_op=False,
            detail=f"child returned unknown install status {invalid_status!r}",
        )

    if returncode != 0:
        status = statuses[0] if len(set(statuses)) == 1 else HarnessInstallStatus.FAILED
        return HarnessInstallEvaluation(
            ok=False,
            status=status,
            no_op=False,
            detail=f"child exited {returncode}: {diagnostic}",
        )

    if not statuses:
        if require_structured:
            return HarnessInstallEvaluation(
                ok=False,
                status=HarnessInstallStatus.FAILED,
                no_op=False,
                detail="structured result is missing a status",
            )
        return HarnessInstallEvaluation(
            ok=True,
            status=HarnessInstallStatus.INSTALLED,
            no_op=False,
            detail="installed (legacy unstructured result)",
        )

    for status in statuses:
        match status:
            case HarnessInstallStatus.INSTALLED:
                continue
            case HarnessInstallStatus.DEGRADED:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=status,
                    no_op=False,
                    detail="degraded install rejected by fail-closed suite policy",
                )
            case HarnessInstallStatus.UNSUPPORTED:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=status,
                    no_op=False,
                    detail="component reports harness unsupported",
                )
            case HarnessInstallStatus.FAILED:
                return HarnessInstallEvaluation(
                    ok=False,
                    status=status,
                    no_op=False,
                    detail="component reports harness installation failed",
                )
            case other:
                assert_never(other)

    return HarnessInstallEvaluation(
        ok=True,
        status=HarnessInstallStatus.INSTALLED,
        no_op=no_op,
        detail="already installed" if no_op else "installed",
    )
