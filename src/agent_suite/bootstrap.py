"""The ordered idempotent bootstrap — run the documented install order.

Implements Plan 001 WI-3.1. ``agent-suite bootstrap [--dry-run] [--tier 0-1|all]
[--user]`` runs the install order from ``docs/bootstrap-contract.md`` §1: each
step is idempotent (re-running a completed step is a no-op), ordered (a step is
gated on the prior step's success), and dry-runnable (``--dry-run`` prints the
plan and acts on nothing). A step that would clobber an existing irreversible
artifact (a signing key, a populated schema) refuses and reports, never
overwrites.

Design (AGENTS.md): thin orchestration — each step shells a component's own
CLI (``regista provision``, ``agent-notes install-harness``, etc.). Injectable
runner + installed check (same pattern as ``doctor.py``) so tests drive the
full ordering against stubbed component CLIs with no real binaries or live
infra. ``assert_never`` over the step-kind and step-status enums so a newly
added kind or status can't slip through ungated. stdlib-only core.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, assert_never

from agent_suite.harness import (
    HarnessTarget,
    expand_harness_target,
    normalize_harness_target,
)
from agent_suite.harness_install import (
    evaluate_install_harness_result,
    install_harness_argv,
    requires_structured_install_result,
)

from agent_suite.components import COMPONENTS, Component, Tier


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as doctor.Runner / lock.VersionRunner)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Closed-set enums (assert_never in every dispatch)
# ---------------------------------------------------------------------------


class StepKind(Enum):
    """The install steps in their fixed order (bootstrap-contract §1)."""

    PROBE_SECRETS = "probe_secrets"
    PROBE_DB = "probe_db"
    PROVISION = "provision"
    FACES = "faces"
    MEMORY_PROVIDER = "memory_provider"
    PROVENANCE = "provenance"
    CAPABILITIES = "capabilities"
    SIGNALING = "signaling"
    USER_ONBOARDING = "user_onboarding"


class StepStatus(Enum):
    """The outcome of a single step.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    PENDING = "pending"
    DONE = "done"
    ALREADY_DONE = "already_done"
    SKIPPED = "skipped"
    FAILED = "failed"
    REFUSED = "refused"


class BootstrapTier(Enum):
    """Which steps to run."""

    CORE_01 = "0-1"
    ALL = "all"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


_INSTALL_ORDER: tuple[StepKind, ...] = (
    StepKind.PROBE_SECRETS,
    StepKind.PROBE_DB,
    StepKind.PROVISION,
    StepKind.FACES,
    StepKind.MEMORY_PROVIDER,
    StepKind.PROVENANCE,
    StepKind.CAPABILITIES,
    StepKind.SIGNALING,
    StepKind.USER_ONBOARDING,
)

_TIER2_STEPS: frozenset[StepKind] = frozenset(
    {StepKind.CAPABILITIES, StepKind.SIGNALING}
)


@dataclass
class StepResult:
    """The outcome of one install step."""

    step: StepKind
    status: StepStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class BootstrapResult:
    """The full bootstrap outcome."""

    ok: bool
    dry_run: bool
    steps: list[StepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# Step implementations
#
# Each step function takes the injectable runner/installed and returns a
# StepResult. Steps that are not yet runnable (component CLI missing) report
# a named failure for spine/face steps, or SKIPPED for optional tier-2 steps.
# ---------------------------------------------------------------------------


def _step_probe_secrets(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
) -> StepResult:
    if not installed("regista"):
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.FAILED,
            "regista CLI not installed — install regista before bootstrapping",
        )
    if dry_run:
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.PENDING,
            "would probe secret backend via regista secrets --list-providers",
        )
    try:
        result = runner(("regista", "secrets", "--list-providers"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.FAILED,
            f"secret-backend probe failed: {exc}",
        )
    if result.returncode != 0:
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.FAILED,
            f"secret backend unreachable: {result.stderr.strip() or 'no detail'}",
        )
    return StepResult(
        StepKind.PROBE_SECRETS, StepStatus.DONE, "secret backend reachable"
    )


def _step_probe_db(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    dsn: str | None,
) -> StepResult:
    if dry_run:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.PENDING,
            "would probe Postgres DSN",
        )
    if not dsn:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            "no DSN configured — set REGISTA_DSN in suite.env",
        )
    probe_cmd: tuple[str, ...] = (
        "regista",
        "doctor",
        "--json",
    )
    if not installed("regista"):
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            "regista CLI not installed — cannot probe Postgres",
        )
    try:
        result = runner(probe_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            f"Postgres probe failed: {exc}",
        )
    if result.returncode != 0:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            f"Postgres unreachable: {result.stderr.strip() or 'no detail'}",
        )
    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            "regista doctor emitted non-JSON stdout",
        )
    reachable = bool(data.get("reachable", False))
    if not reachable:
        return StepResult(
            StepKind.PROBE_DB,
            StepStatus.FAILED,
            f"Postgres not reachable via DSN: {data.get('detail', 'no detail')}",
        )
    return StepResult(StepKind.PROBE_DB, StepStatus.DONE, "Postgres reachable")


def _step_provision(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    project: str | None,
    principal: str | None = None,
) -> StepResult:
    if not installed("regista"):
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            "regista CLI not installed — cannot provision",
        )
    if dry_run:
        return StepResult(
            StepKind.PROVISION,
            StepStatus.PENDING,
            "would provision project schema + service role + principal keys"
            + (f" for {project}" if project else ""),
        )
    if not project:
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            "no project configured — set REGISTA_PROJECT in suite.env",
        )
    prov_cmd: tuple[str, ...] = (
        "regista",
        "provision",
        "--project",
        project,
        "--json",
    )
    try:
        result = runner(prov_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            f"provision failed: {exc}",
        )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "already exists" in stderr.lower():
            return StepResult(
                StepKind.PROVISION,
                StepStatus.ALREADY_DONE,
                f"project {project} already provisioned",
            )
        if "clobber" in stderr.lower() or "refuse" in stderr.lower():
            return StepResult(
                StepKind.PROVISION,
                StepStatus.REFUSED,
                f"provision refused (would clobber existing key/schema): {stderr}",
            )
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            f"provision failed: {stderr or 'no detail'}",
        )
    import json

    already_provisioned = False
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("schema_created") is False:
                already_provisioned = True

    princ_id = principal or "suite-service"
    princ_cmd: tuple[str, ...] = (
        "regista",
        "provision-principal",
        "--project",
        project,
        "--principal",
        princ_id,
        "--json",
    )
    try:
        princ_result = runner(princ_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            f"provision-principal failed: {exc}",
        )
    if princ_result.returncode != 0:
        p_stderr = princ_result.stderr.strip()
        if "clobber" in p_stderr.lower() or "refuse" in p_stderr.lower():
            return StepResult(
                StepKind.PROVISION,
                StepStatus.REFUSED,
                f"provision-principal refused (would clobber existing key for {princ_id}): {p_stderr}",
            )
        if "already" in p_stderr.lower() or "exists" in p_stderr.lower():
            already_provisioned = True
        else:
            return StepResult(
                StepKind.PROVISION,
                StepStatus.FAILED,
                f"provision-principal failed: {p_stderr or 'no detail'}",
            )

    status = StepStatus.ALREADY_DONE if already_provisioned else StepStatus.DONE
    return StepResult(
        StepKind.PROVISION, status, f"project {project} provisioned (principal: {princ_id})"
    )


def _step_install_harness(
    step: StepKind,
    comp: Component,
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    harness: HarnessTarget = HarnessTarget.ALL,
) -> StepResult:
    cli_name = comp.doctor_cmd[0]
    if not installed(cli_name):
        match comp.tier:
            case Tier.SPINE | Tier.FACE:
                return StepResult(
                    step,
                    StepStatus.FAILED,
                    f"{cli_name} not installed — required for tier {comp.tier.value}",
                )
            case Tier.PLUMBING:
                return StepResult(
                    step,
                    StepStatus.SKIPPED,
                    f"{cli_name} not installed (tier: {comp.tier.value}, optional)",
                )
            case other:
                assert_never(other)

    install_cmds = tuple(
        install_harness_argv(cli_name, target)
        for target in expand_harness_target(harness)
    )
    if dry_run:
        return StepResult(
            step,
            StepStatus.PENDING,
            f"would run {'; '.join(' '.join(cmd) for cmd in install_cmds)}",
        )
    already_installed = 0
    for install_cmd in install_cmds:
        try:
            result = runner(install_cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return StepResult(
                step,
                StepStatus.FAILED,
                f"{cli_name} install-harness failed: {exc}",
            )
        evaluation = evaluate_install_harness_result(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            expected_tool=cli_name,
            expected_harness=HarnessTarget(install_cmd[2]),
            require_structured=requires_structured_install_result(cli_name),
        )
        if not evaluation.ok:
            return StepResult(
                step,
                StepStatus.FAILED,
                f"{cli_name} install-harness {install_cmd[2]} "
                f"{evaluation.status.value}: {evaluation.detail}",
            )
        if evaluation.no_op:
            already_installed += 1
    if already_installed == len(install_cmds):
        return StepResult(
            step,
            StepStatus.ALREADY_DONE,
            f"{cli_name} harness targets already installed",
        )
    return StepResult(
        step, StepStatus.DONE, f"{cli_name} harness targets installed"
    )


def _step_memory_provider(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    memory_engine: str,
    hindsight_url: str | None,
) -> StepResult:
    if not installed("agent-notes"):
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            "agent-notes not installed — cannot configure memory provider",
        )
    if dry_run:
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.PENDING,
            f"would configure memory provider (engine: {memory_engine})",
        )
    if memory_engine == "native":
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.DONE,
            "memory provider: native (no external configuration needed)",
        )
    if memory_engine != "hindsight":
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            f"unknown memory engine: {memory_engine}",
        )
    if not hindsight_url:
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            "hindsight engine selected but HINDSIGHT_URL not set",
        )
    describe_cmd: tuple[str, ...] = (
        "agent-notes", "memory-provider", "describe", "--json",
    )
    try:
        result = runner(describe_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            f"memory-provider describe failed: {exc}",
        )
    if result.returncode != 0:
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            f"hindsight unreachable: {result.stderr.strip() or 'no detail'}",
        )
    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            "hindsight describe emitted non-JSON stdout",
        )
    if not isinstance(data, dict):
        return StepResult(
            StepKind.MEMORY_PROVIDER,
            StepStatus.FAILED,
            "hindsight describe emitted JSON but not a dict",
        )
    engine_name = data.get("engine", "unknown")
    return StepResult(
        StepKind.MEMORY_PROVIDER,
        StepStatus.DONE,
        f"memory provider: hindsight (engine: {engine_name}) reachable at {hindsight_url}",
    )


def _step_user_onboarding(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    user: str | None,
    config_path: str | None,
) -> StepResult:
    if not user:
        return StepResult(
            StepKind.USER_ONBOARDING,
            StepStatus.SKIPPED,
            "no --user specified; skipping per-user onboarding",
        )
    if dry_run:
        return StepResult(
            StepKind.USER_ONBOARDING,
            StepStatus.PENDING,
            f"would write per-user overlay for {user}",
        )
    return StepResult(
        StepKind.USER_ONBOARDING,
        StepStatus.SKIPPED,
        "user onboarding not yet implemented (Plan 001 WI-3.3)",
    )


# ---------------------------------------------------------------------------
# Step dispatch
# ---------------------------------------------------------------------------


def _run_step(
    step: StepKind,
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    tier: BootstrapTier,
    project: str | None,
    dsn: str | None,
    user: str | None,
    config_path: str | None,
    harness: HarnessTarget,
    memory_engine: str = "native",
    hindsight_url: str | None = None,
) -> StepResult:
    match step:
        case StepKind.PROBE_SECRETS:
            return _step_probe_secrets(runner=runner, installed=installed, dry_run=dry_run)
        case StepKind.PROBE_DB:
            return _step_probe_db(
                runner=runner, installed=installed, dry_run=dry_run, dsn=dsn
            )
        case StepKind.PROVISION:
            return _step_provision(
                runner=runner, installed=installed, dry_run=dry_run, project=project
            )
        case StepKind.FACES:
            comp = next(c for c in COMPONENTS if c.ident == "agent-notes")
            return _step_install_harness(
                step, comp, runner=runner, installed=installed, dry_run=dry_run, harness=harness
            )
        case StepKind.MEMORY_PROVIDER:
            return _step_memory_provider(
                runner=runner,
                installed=installed,
                dry_run=dry_run,
                memory_engine=memory_engine,
                hindsight_url=hindsight_url,
            )
        case StepKind.PROVENANCE:
            comp = next(c for c in COMPONENTS if c.ident == "agent-provenance")
            return _step_install_harness(
                step, comp, runner=runner, installed=installed, dry_run=dry_run, harness=harness
            )
        case StepKind.CAPABILITIES:
            comp = next(c for c in COMPONENTS if c.ident == "agent-capability-broker")
            return _step_install_harness(
                step, comp, runner=runner, installed=installed, dry_run=dry_run, harness=harness
            )
        case StepKind.SIGNALING:
            comp = next(c for c in COMPONENTS if c.ident == "agent-wake")
            return _step_install_harness(
                step, comp, runner=runner, installed=installed, dry_run=dry_run, harness=harness
            )
        case StepKind.USER_ONBOARDING:
            return _step_user_onboarding(
                runner=runner,
                installed=installed,
                dry_run=dry_run,
                user=user,
                config_path=config_path,
            )
        case other:
            assert_never(other)


def _steps_for_tier(tier: BootstrapTier) -> list[StepKind]:
    match tier:
        case BootstrapTier.CORE_01:
            return [s for s in _INSTALL_ORDER if s not in _TIER2_STEPS]
        case BootstrapTier.ALL:
            return list(_INSTALL_ORDER)
        case other:
            assert_never(other)


def _is_terminal(status: StepStatus) -> bool:
    """A step that stops the pipeline (failure or refusal)."""
    match status:
        case StepStatus.FAILED | StepStatus.REFUSED:
            return True
        case StepStatus.DONE | StepStatus.ALREADY_DONE | StepStatus.SKIPPED | StepStatus.PENDING:
            return False
        case other:
            assert_never(other)


def _compute_ok(steps: list[StepResult]) -> bool:
    for s in steps:
        match s.status:
            case StepStatus.FAILED | StepStatus.REFUSED:
                return False
            case (
                StepStatus.DONE
                | StepStatus.ALREADY_DONE
                | StepStatus.SKIPPED
                | StepStatus.PENDING
            ):
                continue
            case other:
                assert_never(other)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_bootstrap(
    *,
    dry_run: bool = False,
    tier: str = "0-1",
    user: str | None = None,
    project: str | None = None,
    dsn: str | None = None,
    harness: HarnessTarget = HarnessTarget.ALL,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    config_path: str | None = None,
    memory_engine: str = "native",
    hindsight_url: str | None = None,
) -> BootstrapResult:
    """Run the documented install order idempotently.

    Each step is gated on the prior step's success. ``dry_run`` prints the plan
    without acting. A step that would clobber an existing key or schema refuses.
    Missing external dependencies fail with a named, actionable message.
    ``memory_engine`` and ``hindsight_url`` control the MEMORY_PROVIDER step
    (Plan 012 WI-1.2): native is a no-op; hindsight verifies reachability.
    """
    harness = normalize_harness_target(harness)
    tier_enum = BootstrapTier(tier)
    steps_to_run = _steps_for_tier(tier_enum)

    if user and StepKind.USER_ONBOARDING not in steps_to_run:
        steps_to_run.append(StepKind.USER_ONBOARDING)

    results: list[StepResult] = []
    for step in steps_to_run:
        result = _run_step(
            step,
            runner=runner,
            installed=installed,
            dry_run=dry_run,
            tier=tier_enum,
            project=project,
            dsn=dsn,
            user=user,
            config_path=config_path,
            harness=harness,
            memory_engine=memory_engine,
            hindsight_url=hindsight_url,
        )
        results.append(result)
        if _is_terminal(result.status):
            remaining = [
                StepResult(s, StepStatus.SKIPPED, f"skipped: prior step {result.step.value} did not succeed")
                for s in steps_to_run
                if s != step and s not in {r.step for r in results}
            ]
            results.extend(remaining)
            break

    return BootstrapResult(
        ok=_compute_ok(results),
        dry_run=dry_run,
        steps=results,
    )


def format_text(result: BootstrapResult) -> str:
    """Human-readable summary for ``bootstrap`` without ``--json``."""
    lines: list[str] = []
    if result.dry_run:
        lines.append("agent-suite bootstrap --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite bootstrap")
    lines.append("")
    for s in result.steps:
        lines.append(f"  {s.step.value:<18} {s.status.value:<14} {s.detail}")
    lines.append("")
    lines.append(f"bootstrap: {'OK' if result.ok else 'NOT OK'}")
    return "\n".join(lines)
