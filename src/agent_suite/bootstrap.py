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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite import identity, secret_refs
from agent_suite._redact import redact_url
from agent_suite.component_result import evaluate_component_result
from agent_suite.components import COMPONENTS, Component, Tier
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
from agent_suite.provisioning import (
    ProvisionOutcome,
    default_principal,
    provision_projects,
)

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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)


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
    PROJECTIONS = "projections"
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
    StepKind.PROJECTIONS,
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
    env: Mapping[str, str],
    load_key_file: secret_refs.KeyFileLoader | None = None,
) -> StepResult:
    """Resolve every configured secret ref — do not merely list providers.

    WI-041. ``regista secrets --list-providers`` proves a provider *class is
    registered*, which is why this step reported "secret backend reachable" on a
    host whose only ``vault:`` ref was provably 403. What
    ``docs/secrets-vault.md`` §8 promises is resolution, so that is what this
    does: enumerate the refs this host's resolved config actually names, then
    resolve each one, naming the failing ref.

    The step never reads the child's stdout on the resolve path — ``regista
    secrets --ref`` prints the resolved secret there.
    """
    if not installed("regista"):
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.FAILED,
            "regista CLI not installed — install regista before bootstrapping",
        )
    refs = (
        secret_refs.discover_refs(env)
        if load_key_file is None
        else secret_refs.discover_refs(env, load_key_file=load_key_file)
    )
    problems = secret_refs.config_problems(env)
    if dry_run:
        planned = (
            f"would resolve {len(refs)} configured secret ref(s) "
            f"({', '.join(r.source for r in refs)})"
            if refs
            else "would probe the resolver; no backend secret refs are configured"
        )
        return StepResult(StepKind.PROBE_SECRETS, StepStatus.PENDING, planned)

    if problems:
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.FAILED,
            "secret configuration cannot resolve: " + "; ".join(problems),
        )

    if not refs:
        # No refs to resolve, so the honest claim is only that the resolver
        # runs — say that, not "reachable".
        try:
            listing = runner(("regista", "secrets", "--list-providers"))
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return StepResult(
                StepKind.PROBE_SECRETS,
                StepStatus.FAILED,
                f"secret-resolver probe failed: {exc}",
            )
        if listing.returncode != 0:
            return StepResult(
                StepKind.PROBE_SECRETS,
                StepStatus.FAILED,
                f"secret resolver unavailable: "
                f"{listing.stderr.strip() or 'no detail'}",
            )
        return StepResult(
            StepKind.PROBE_SECRETS,
            StepStatus.DONE,
            "no backend secret refs are configured; resolver available but "
            "nothing to resolve (key material is local)",
        )

    for ref in refs:
        static = secret_refs.ref_static_problem(ref.ref)
        if static is not None:
            return StepResult(
                StepKind.PROBE_SECRETS,
                StepStatus.FAILED,
                f"{ref.source} cannot resolve: {static}",
            )
        argv = secret_refs.probe_ref_argv(ref.ref)
        try:
            probe = runner(argv)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return StepResult(
                StepKind.PROBE_SECRETS,
                StepStatus.FAILED,
                f"could not resolve {ref.source} ({ref.ref}): {exc}",
            )
        if probe.returncode != 0:
            # Only the failure path may look at stdout: on success it is the
            # resolved secret. On failure it is the CLI-contract envelope.
            verdict = evaluate_component_result(
                command=f"regista secrets --ref {ref.ref}",
                returncode=probe.returncode,
                stdout=probe.stdout,
                stderr=probe.stderr,
            )
            return StepResult(
                StepKind.PROBE_SECRETS,
                StepStatus.FAILED,
                f"{ref.source} does not resolve: {verdict.detail}",
            )

    foreign = sorted({r.owner_cli for r in refs if r.owner_cli != "regista"})
    caveat = (
        ""
        if not foreign
        else (
            f"; resolution proven in regista's environment only — "
            f"{', '.join(foreign)} must also be able to import the backend "
            f"client in its own venv, which its own doctor is the check for"
        )
    )
    return StepResult(
        StepKind.PROBE_SECRETS,
        StepStatus.DONE,
        f"resolved {len(refs)} configured secret ref(s): "
        f"{', '.join(r.source for r in refs)}{caveat}",
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


def _provision_status_for(outcome: ProvisionOutcome) -> StepStatus:
    match outcome:
        case ProvisionOutcome.DONE:
            return StepStatus.DONE
        case ProvisionOutcome.ALREADY_DONE:
            return StepStatus.ALREADY_DONE
        case ProvisionOutcome.REFUSED:
            return StepStatus.REFUSED
        case ProvisionOutcome.FAILED:
            return StepStatus.FAILED
        case other:
            assert_never(other)


def _step_provision(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    projects: Sequence[str],
    principal: str | None = None,
) -> StepResult:
    """Provision every project slug the config names (WI-040, WI-042, WI-051).

    The verdict comes from :mod:`agent_suite.provisioning`, which reads the
    child's structured envelope: a ``regista provision --json`` that exits 0
    with an ``error`` body fails this step instead of greening it, and a
    ``provision-principal`` refusal is recognised by its error code rather than
    by the words in its message.
    """
    if not installed("regista"):
        return StepResult(
            StepKind.PROVISION,
            StepStatus.FAILED,
            "regista CLI not installed — cannot provision",
        )
    princ_id = default_principal(principal)
    if dry_run:
        listed = ", ".join(projects) if projects else "(no project configured)"
        return StepResult(
            StepKind.PROVISION,
            StepStatus.PENDING,
            f"would provision schema + service role + principal keys for "
            f"{listed} (principal: {princ_id})",
        )
    report = provision_projects(runner=runner, projects=projects, principal=princ_id)
    return StepResult(
        StepKind.PROVISION, _provision_status_for(report.outcome), report.detail
    )


def _step_projections(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
) -> StepResult:
    """Migrate agent-notes' projection database (WI-043).

    ``agent-notes install-harness`` wires skills and env; it does not touch
    agent-notes' own projection schema. After a bootstrap that printed
    ``bootstrap: OK``, its doctor reported 11 missing tables/views and the
    remedy appeared only in a troubleshooting table. So the migration is an
    explicit, ordered, idempotent step here.

    It is idempotent *by verifying first*: the check is agent-notes' own
    ``schema_up_to_date`` doctor check, so a converged host reports
    ``already_done`` without running any DDL, and a host that needed migrating
    is only reported ``done`` once that same check passes. A skipped or absent
    check is not a pass.
    """
    if not installed("agent-notes"):
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.FAILED,
            "agent-notes not installed — required for tier face",
        )
    if dry_run:
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.PENDING,
            "would verify agent-notes' projection schema and run "
            "agent-notes-migrate --all if it is not up to date",
        )

    before = _schema_check(runner)
    if before is True:
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.ALREADY_DONE,
            "agent-notes projection schema already up to date",
        )
    if not installed("agent-notes-migrate"):
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.FAILED,
            "agent-notes projection schema is not up to date and "
            "agent-notes-migrate is not installed — the migration cannot be "
            "run on this host (agent-notes WI-047: the wheel must ship "
            "schema/*.sql for an artifact-only install)",
        )
    try:
        migrate = runner(("agent-notes-migrate", "--all"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.FAILED,
            f"agent-notes-migrate --all could not run: {exc}",
        )
    if migrate.returncode != 0:
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.FAILED,
            f"agent-notes-migrate --all exited {migrate.returncode}: "
            f"{migrate.stderr.strip() or migrate.stdout.strip() or 'no detail'}",
        )
    after = _agent_notes_schema_check(runner)
    if after is None or after.get("status") != "ok":
        detail = (
            "agent-notes doctor did not report a schema_up_to_date check"
            if after is None
            else f"{after.get('status')}: {after.get('detail', 'no detail')}"
        )
        return StepResult(
            StepKind.PROJECTIONS,
            StepStatus.FAILED,
            f"agent-notes-migrate --all exited 0 but agent-notes' "
            f"schema_up_to_date check still does not pass ({detail})",
        )
    return StepResult(
        StepKind.PROJECTIONS,
        StepStatus.DONE,
        "agent-notes projection schema migrated (schema_up_to_date verified)",
    )


#: The agent-notes doctor check that answers "is the projection schema present".
_SCHEMA_CHECK_NAME = "schema_up_to_date"


def _agent_notes_schema_check(runner: Runner) -> dict[str, object] | None:
    """The ``schema_up_to_date`` check from ``agent-notes doctor --json``.

    Returns ``None`` when the check cannot be read at all — which callers must
    treat as "not verified", never as a pass.
    """
    import json

    try:
        result = runner(("agent-notes", "doctor", "--json"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    checks = data.get("checks")
    if not isinstance(checks, list):
        return None
    for check in checks:
        if isinstance(check, dict) and check.get("name") == _SCHEMA_CHECK_NAME:
            return check
    return None


def _schema_check(runner: Runner) -> bool | None:
    """``True`` only when agent-notes affirmatively reports the schema is fine."""
    check = _agent_notes_schema_check(runner)
    if check is None:
        return None
    return check.get("status") == "ok"


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
        f"memory provider: hindsight (engine: {engine_name}) "
        f"reachable at {redact_url(hindsight_url)}",
    )


def _step_user_onboarding(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    user: str | None,
    config_path: str | None,
    env: Mapping[str, str],
    dossier_user: str | None = None,
) -> StepResult:
    if not user:
        return StepResult(
            StepKind.USER_ONBOARDING,
            StepStatus.SKIPPED,
            "no --user specified; skipping per-user onboarding",
        )
    result = identity.run_user_onboarding(
        principal=user,
        overlay_path=Path(config_path) if config_path else None,
        dry_run=dry_run,
        runner=runner,
        installed=installed,
        env=env,
        dossier_user=dossier_user,
    )
    detail = "; ".join(f"{s.name}: {s.detail}" for s in result.steps)
    return StepResult(
        StepKind.USER_ONBOARDING,
        _step_status_for(result.outcome),
        detail,
    )


def _step_status_for(outcome: identity.IdentityOutcome) -> StepStatus:
    """Map an identity outcome onto a bootstrap step status.

    ``MANUAL`` has no bootstrap equivalent — onboarding never produces it —
    but it is mapped rather than dropped so adding a step that can return it
    cannot silently degrade to a success.
    """
    match outcome:
        case identity.IdentityOutcome.DONE:
            return StepStatus.DONE
        case identity.IdentityOutcome.ALREADY_DONE:
            return StepStatus.ALREADY_DONE
        case identity.IdentityOutcome.PENDING:
            return StepStatus.PENDING
        case identity.IdentityOutcome.MANUAL:
            return StepStatus.REFUSED
        case identity.IdentityOutcome.REFUSED:
            return StepStatus.REFUSED
        case identity.IdentityOutcome.FAILED:
            return StepStatus.FAILED
        case other:
            assert_never(other)


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
    projects: Sequence[str],
    dsn: str | None,
    user: str | None,
    config_path: str | None,
    harness: HarnessTarget,
    env: Mapping[str, str],
    memory_engine: str = "native",
    hindsight_url: str | None = None,
    load_key_file: secret_refs.KeyFileLoader | None = None,
    dossier_user: str | None = None,
) -> StepResult:
    match step:
        case StepKind.PROBE_SECRETS:
            return _step_probe_secrets(
                runner=runner,
                installed=installed,
                dry_run=dry_run,
                env=env,
                load_key_file=load_key_file,
            )
        case StepKind.PROBE_DB:
            return _step_probe_db(
                runner=runner, installed=installed, dry_run=dry_run, dsn=dsn
            )
        case StepKind.PROVISION:
            return _step_provision(
                runner=runner, installed=installed, dry_run=dry_run, projects=projects
            )
        case StepKind.PROJECTIONS:
            return _step_projections(
                runner=runner, installed=installed, dry_run=dry_run
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
                env=env,
                dossier_user=dossier_user,
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


def _merge_projects(project: str | None, projects: Sequence[str]) -> tuple[str, ...]:
    """Ordered, deduplicated project slugs — the primary one first."""
    ordered: list[str] = []
    for slug in ((project,) if project else ()) + tuple(projects):
        cleaned = slug.strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return tuple(ordered)


def run_bootstrap(
    *,
    dry_run: bool = False,
    tier: str = "0-1",
    user: str | None = None,
    project: str | None = None,
    projects: Sequence[str] = (),
    dsn: str | None = None,
    harness: HarnessTarget = HarnessTarget.ALL,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    config_path: str | None = None,
    memory_engine: str = "native",
    hindsight_url: str | None = None,
    env: Mapping[str, str] | None = None,
    load_key_file: secret_refs.KeyFileLoader | None = None,
    dossier_user: str | None = None,
) -> BootstrapResult:
    """Run the documented install order idempotently.

    Each step is gated on the prior step's success. ``dry_run`` prints the plan
    without acting. A step that would clobber an existing key or schema refuses.
    Missing external dependencies fail with a named, actionable message.
    ``memory_engine`` and ``hindsight_url`` control the MEMORY_PROVIDER step
    (Plan 012 WI-1.2): native is a no-op; hindsight verifies reachability.

    ``project`` is the primary (``REGISTA_PROJECT``) slug; ``projects`` is every
    slug the resolved config names, which is what actually gets provisioned —
    ``CAIRN_PROJECT`` is usually a *different* slug and used to be left
    unprovisioned (WI-042). ``env`` is the resolved suite environment, read by
    the secret-ref probe and the dossier identity binding; it defaults to
    ``os.environ``.
    """
    import os

    harness = normalize_harness_target(harness)
    tier_enum = BootstrapTier(tier)
    steps_to_run = _steps_for_tier(tier_enum)
    resolved_env: Mapping[str, str] = os.environ if env is None else env
    all_projects = _merge_projects(project, projects)

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
            projects=all_projects,
            dsn=dsn,
            user=user,
            config_path=config_path,
            harness=harness,
            env=resolved_env,
            memory_engine=memory_engine,
            hindsight_url=hindsight_url,
            load_key_file=load_key_file,
            dossier_user=dossier_user,
        )
        results.append(result)
        if _is_terminal(result.status):
            remaining = [
                StepResult(
                    s,
                    StepStatus.SKIPPED,
                    f"skipped: prior step {result.step.value} did not succeed",
                )
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
