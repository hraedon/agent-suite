"""The one deployment front door — profile-driven end-to-end deploy.

Implements Plan 008 WI-3.2 / Plan 009 WI-4.1. ``agent-suite deploy`` composes the
existing operations (preflight, bootstrap, onboard, lock, doctor) into a single
profile-driven flow. Each step is idempotent (inherited from the composed
modules), ordered (a step is gated on the prior step's success), and dry-
runnable (``--dry-run`` prints the plan and acts on nothing).

Design (AGENTS.md): thin orchestration — this module composes ``bootstrap``,
``onboard``, ``lock``, and ``doctor`` via their public APIs; it never
reimplements them. Injectable runner + installed check (same Protocol pattern
as ``bootstrap.py``) so tests drive the full flow against stubbed component
CLIs. ``assert_never`` over the step and step-status enums so a newly added
kind or status can't slip through ungated. stdlib-only core. No secrets in any
output — the dry-run plan contains no secret values. No work-domain
identifiers — placeholders only.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.bootstrap import run_bootstrap
from agent_suite.harness import HarnessTarget, normalize_harness_target
from agent_suite.components import COMPONENTS
from agent_suite.doctor import aggregate
from agent_suite.lock import (
    check_drift,
    generate_lock,
    load_lock_file,
    read_regista_quad,
    write_lock_file,
)
from agent_suite.onboard import run_onboard
from agent_suite.profiles import PROFILE_REQUIREMENTS, Profile
from agent_suite.runtime_provenance import read_runtime_revisions


class Runner(Protocol):
    """Run a component CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


class DeployStep(Enum):
    """The deploy steps in their fixed order (Plan 008 §5.2)."""

    PREFLIGHT = "preflight"
    BOOTSTRAP = "bootstrap"
    ONBOARD = "onboard"
    LOCK = "lock"
    DOCTOR = "doctor"


class DeployStepStatus(Enum):
    """The outcome of a single deploy step.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    PENDING = "pending"
    DONE = "done"
    ALREADY_DONE = "already_done"
    SKIPPED = "skipped"
    FAILED = "failed"
    REFUSED = "refused"


@dataclass
class DeployStepResult:
    """The outcome of one deploy step."""

    step: DeployStep
    status: DeployStepStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class DeployResult:
    """The full deploy outcome."""

    ok: bool
    dry_run: bool
    profile: str
    steps: list[DeployStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "steps": [s.to_dict() for s in self.steps],
        }


_DEPLOY_ORDER: tuple[DeployStep, ...] = (
    DeployStep.PREFLIGHT,
    DeployStep.BOOTSTRAP,
    DeployStep.ONBOARD,
    DeployStep.LOCK,
    DeployStep.DOCTOR,
)


def _required_clis_for_profile(profile: str) -> set[str]:
    """Derive the required CLI names for a profile from PROFILE_REQUIREMENTS."""
    profile_enum = Profile(profile)
    required_idents = PROFILE_REQUIREMENTS[profile_enum]
    clis: set[str] = set()
    for comp in COMPONENTS:
        if comp.ident in required_idents:
            clis.add(comp.doctor_cmd[0])
    return clis


def _step_preflight(
    *,
    profile: str,
    installed: Installed,
    dry_run: bool,
) -> DeployStepResult:
    required = _required_clis_for_profile(profile)
    sorted_required = sorted(required)
    if dry_run:
        return DeployStepResult(
            DeployStep.PREFLIGHT,
            DeployStepStatus.PENDING,
            f"would check required CLIs: {', '.join(sorted_required)}",
        )
    missing = sorted(cli for cli in required if not installed(cli))
    if missing:
        return DeployStepResult(
            DeployStep.PREFLIGHT,
            DeployStepStatus.FAILED,
            f"missing required CLIs: {', '.join(missing)}",
        )
    return DeployStepResult(
        DeployStep.PREFLIGHT,
        DeployStepStatus.DONE,
        f"all required CLIs installed ({', '.join(sorted_required)})",
    )


def _step_bootstrap(
    *,
    dry_run: bool,
    profile: str,
    project: str | None,
    dsn: str | None,
    user: str | None,
    harness: HarnessTarget,
    memory_engine: str,
    hindsight_url: str | None,
    runner: Runner,
    installed: Installed,
) -> DeployStepResult:
    tier = "all" if profile == "C" else "0-1"
    bs_result = run_bootstrap(
        dry_run=dry_run,
        tier=tier,
        user=user,
        project=project,
        dsn=dsn,
        harness=harness,
        memory_engine=memory_engine,
        hindsight_url=hindsight_url,
        runner=runner,
        installed=installed,
    )
    if not bs_result.ok:
        detail = "bootstrap failed"
        for s in bs_result.steps:
            if s.status.value in ("failed", "refused"):
                detail = s.detail
                break
        return DeployStepResult(DeployStep.BOOTSTRAP, DeployStepStatus.FAILED, detail)
    if dry_run:
        return DeployStepResult(
            DeployStep.BOOTSTRAP,
            DeployStepStatus.PENDING,
            f"would run bootstrap (tier: {tier})",
        )
    all_already = all(
        s.status.value in ("already_done", "skipped") for s in bs_result.steps
    )
    status = DeployStepStatus.ALREADY_DONE if all_already else DeployStepStatus.DONE
    return DeployStepResult(
        DeployStep.BOOTSTRAP,
        status,
        f"bootstrap complete (tier: {tier})",
    )


def _step_onboard(
    *,
    dry_run: bool,
    profile: str,
    project: str | None,
    spec_path: Path | None,
    harness: HarnessTarget,
    principal: str | None,
    runner: Runner,
    installed: Installed,
) -> DeployStepResult:
    if profile == "A":
        return DeployStepResult(
            DeployStep.ONBOARD,
            DeployStepStatus.SKIPPED,
            "profile A does not require project onboarding",
        )
    if not project:
        return DeployStepResult(
            DeployStep.ONBOARD,
            DeployStepStatus.SKIPPED,
            "no project specified",
        )
    ob_result = run_onboard(
        project=project,
        spec_path=spec_path,
        dry_run=dry_run,
        harness=harness,
        principal=principal,
        runner=runner,
        installed=installed,
    )
    if not ob_result.ok:
        detail = "onboard failed"
        for s in ob_result.steps:
            if s.status.value in ("failed", "refused"):
                detail = s.detail
                break
        return DeployStepResult(DeployStep.ONBOARD, DeployStepStatus.FAILED, detail)
    if dry_run:
        return DeployStepResult(
            DeployStep.ONBOARD,
            DeployStepStatus.PENDING,
            f"would onboard project {project}",
        )
    return DeployStepResult(
        DeployStep.ONBOARD,
        DeployStepStatus.DONE,
        f"project {project} onboarded",
    )


def _step_lock(
    *,
    dry_run: bool,
    memory_engine: str,
    runner: Runner,
    installed: Installed,
) -> DeployStepResult:
    if dry_run:
        return DeployStepResult(
            DeployStep.LOCK,
            DeployStepStatus.PENDING,
            "would check or create SUITE.lock",
        )
    report = aggregate(installed=installed, runner=runner)
    component_versions: dict[str, str | None] = {
        r.component: r.version for r in report.components
    }
    try:
        component_revisions = read_runtime_revisions()
    except RuntimeError as exc:
        return DeployStepResult(
            DeployStep.LOCK,
            DeployStepStatus.FAILED,
            f"runtime revision provenance unavailable: {exc}",
        )
    try:
        existing = load_lock_file()
    except ValueError as exc:
        return DeployStepResult(
            DeployStep.LOCK,
            DeployStepStatus.FAILED,
            f"SUITE.lock unreadable: {exc}",
        )
    if existing is not None:
        current_quad = read_regista_quad(runner=runner, installed=installed)
        drift_result = check_drift(
            existing,
            current_quad=current_quad,
            component_versions=component_versions,
            component_revisions=component_revisions,
        )
        if drift_result.matches is True:
            return DeployStepResult(
                DeployStep.LOCK,
                DeployStepStatus.ALREADY_DONE,
                "SUITE.lock exists and matches",
            )
        drift_count = len(drift_result.drift)
        return DeployStepResult(
            DeployStep.LOCK,
            DeployStepStatus.DONE,
            f"SUITE.lock drift: {drift_count} drift(s) detected"
            " — run `agent-suite lock` to regenerate",
        )
    lock = generate_lock(
        component_versions=component_versions,
        component_revisions=component_revisions,
        runner=runner,
        installed=installed,
        memory_engine=memory_engine,
    )
    write_lock_file(lock)
    return DeployStepResult(
        DeployStep.LOCK,
        DeployStepStatus.DONE,
        "SUITE.lock generated and written",
    )


def _step_doctor(
    *,
    dry_run: bool,
    profile: str,
    runner: Runner,
    installed: Installed,
) -> DeployStepResult:
    if dry_run:
        return DeployStepResult(
            DeployStep.DOCTOR,
            DeployStepStatus.SKIPPED,
            "skipped in dry-run (read-only check)",
        )
    profile_enum = Profile(profile)
    import os

    from agent_suite.components import shared_service_components
    from agent_suite.config import MemoryProviderConfig

    shared_endpoints: dict[str, str] = {}
    for comp in shared_service_components():
        url = os.environ.get(comp.endpoint_env_var)
        if url:
            shared_endpoints[comp.ident] = url
    report = aggregate(
        installed=installed,
        runner=runner,
        profile=profile_enum,
        shared_endpoints=shared_endpoints or None,
        memory_provider_config=MemoryProviderConfig.from_env(),
    )
    if report.suite_ok:
        return DeployStepResult(
            DeployStep.DOCTOR,
            DeployStepStatus.DONE,
            "suite: OK",
        )
    failed_components = [
        r.component for r in report.components if r.status.value == "failed"
    ]
    detail = "suite: NOT OK"
    if failed_components:
        detail += f" (failed: {', '.join(failed_components)})"
    return DeployStepResult(
        DeployStep.DOCTOR,
        DeployStepStatus.FAILED,
        detail,
    )


def _run_step(
    step: DeployStep,
    *,
    dry_run: bool,
    profile: str,
    project: str | None,
    spec_path: Path | None,
    harness: HarnessTarget,
    principal: str | None,
    user: str | None,
    dsn: str | None,
    memory_engine: str,
    hindsight_url: str | None,
    runner: Runner,
    installed: Installed,
) -> DeployStepResult:
    match step:
        case DeployStep.PREFLIGHT:
            return _step_preflight(
                profile=profile, installed=installed, dry_run=dry_run
            )
        case DeployStep.BOOTSTRAP:
            return _step_bootstrap(
                dry_run=dry_run,
                profile=profile,
                project=project,
                dsn=dsn,
                user=user,
                harness=harness,
                memory_engine=memory_engine,
                hindsight_url=hindsight_url,
                runner=runner,
                installed=installed,
            )
        case DeployStep.ONBOARD:
            return _step_onboard(
                dry_run=dry_run,
                profile=profile,
                project=project,
                spec_path=spec_path,
                harness=harness,
                principal=principal,
                runner=runner,
                installed=installed,
            )
        case DeployStep.LOCK:
            return _step_lock(
                dry_run=dry_run,
                memory_engine=memory_engine,
                runner=runner,
                installed=installed,
            )
        case DeployStep.DOCTOR:
            return _step_doctor(
                dry_run=dry_run,
                profile=profile,
                runner=runner,
                installed=installed,
            )
        case other:
            assert_never(other)


def _is_terminal(status: DeployStepStatus) -> bool:
    match status:
        case DeployStepStatus.FAILED | DeployStepStatus.REFUSED:
            return True
        case (
            DeployStepStatus.DONE
            | DeployStepStatus.ALREADY_DONE
            | DeployStepStatus.SKIPPED
            | DeployStepStatus.PENDING
        ):
            return False
        case other:
            assert_never(other)


def _compute_ok(steps: list[DeployStepResult]) -> bool:
    for s in steps:
        match s.status:
            case DeployStepStatus.FAILED | DeployStepStatus.REFUSED:
                return False
            case (
                DeployStepStatus.DONE
                | DeployStepStatus.ALREADY_DONE
                | DeployStepStatus.SKIPPED
                | DeployStepStatus.PENDING
            ):
                continue
            case other:
                assert_never(other)
    return True


def run_deploy(
    *,
    dry_run: bool = False,
    profile: str = "A",
    project: str | None = None,
    spec_path: Path | None = None,
    harness: HarnessTarget = HarnessTarget.ALL,
    principal: str | None = None,
    user: str | None = None,
    dsn: str | None = None,
    memory_engine: str = "native",
    hindsight_url: str | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> DeployResult:
    """Run the profile-driven end-to-end deploy flow.

    Composes preflight, bootstrap, onboard, lock, and doctor into one ordered
    pipeline. Each step is gated on the prior step's success — a FAILED or
    REFUSED step stops the pipeline and remaining steps are SKIPPED.
    ``dry_run`` prints the entire plan without acting. ``profile`` selects A/B/C
    and controls which steps run and what each step does. No secrets appear in
    any output.
    """
    harness = normalize_harness_target(harness)
    results: list[DeployStepResult] = []
    for step in _DEPLOY_ORDER:
        result = _run_step(
            step,
            dry_run=dry_run,
            profile=profile,
            project=project,
            spec_path=spec_path,
            harness=harness,
            principal=principal,
            user=user,
            dsn=dsn,
            memory_engine=memory_engine,
            hindsight_url=hindsight_url,
            runner=runner,
            installed=installed,
        )
        results.append(result)
        if _is_terminal(result.status):
            remaining = [
                DeployStepResult(
                    s,
                    DeployStepStatus.SKIPPED,
                    f"skipped: prior step {result.step.value} did not succeed",
                )
                for s in _DEPLOY_ORDER
                if s != step and s not in {r.step for r in results}
            ]
            results.extend(remaining)
            break
    return DeployResult(
        ok=_compute_ok(results),
        dry_run=dry_run,
        profile=profile,
        steps=results,
    )


def format_text(result: DeployResult) -> str:
    """Human-readable summary for ``deploy`` without ``--json``."""
    lines: list[str] = []
    if result.dry_run:
        lines.append("agent-suite deploy --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite deploy")
    lines.append(f"  profile: {result.profile}")
    lines.append("")
    for s in result.steps:
        lines.append(f"  {s.step.value:<12} {s.status.value:<14} {s.detail}")
    lines.append("")
    lines.append(f"deploy: {'OK' if result.ok else 'NOT OK'}")
    return "\n".join(lines)
