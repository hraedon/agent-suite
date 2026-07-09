"""Project-onboarding front door — spec -> provision -> sign event-zero.

Implements Plan 001 WI-3.3.  ``agent-suite onboard <slug> [--spec spec.yaml]``
is the compelling integration: a project is born from a signed spec.  On
enrollment, the spec.yaml (+ spec.md hash) is signed into regista as the
project's **event zero**, so the audit chain runs spec -> work -> review ->
done, all verifiable.

The flow:
1. Read/validate the spec.yaml (if provided) — check it is readable, extract
   the schema version for interchange discipline.
2. Run ``regista provision`` for the project (schemas + service role +
   principal keys — idempotent).
3. Sign the spec.yaml (+ spec.md hash) as event-zero via ``regista spec sign``
   (Plan 025 WI-4.3: "Regista does not parse the spec; it stores and signs it").
4. Wire the project's harness (``install-harness`` for Claude + opencode —
   dual-target, blueprint section 4 hard constraint).

Idempotent: re-running onboards nothing new if the project + spec already
exist.  ``--dry-run`` prints the plan without acting.  No-spec is allowed (a
project without a founding spec is valid, just unanchored, and says so).

Design (AGENTS.md): thin orchestration — each step shells a component's own
CLI (``regista provision``, ``regista spec sign``, component
``install-harness``).  Injectable runner + installed check (same pattern as
``bootstrap.py``) so tests drive the full flow against stubbed component CLIs
with no real binaries or live infra.  ``assert_never`` over the step-kind and
step-status enums so a newly added kind or status can't slip through
ungated.  stdlib-only core.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as bootstrap.Runner / doctor.Runner)
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


class OnboardStep(Enum):
    """The onboarding steps in their fixed order."""

    VALIDATE_SPEC = "validate_spec"
    PROVISION = "provision"
    SIGN_SPEC = "sign_spec"
    WIRE_HARNESS = "wire_harness"


class OnboardStatus(Enum):
    """The outcome of a single onboarding step.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    PENDING = "pending"
    DONE = "done"
    ALREADY_DONE = "already_done"
    SKIPPED = "skipped"
    FAILED = "failed"
    REFUSED = "refused"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Spec schema versions this layer recognises (interchange discipline).
#: An unrecognised version is flagged, not silently accepted (WI-3.3 AC).
RECOGNIZED_SPEC_VERSIONS: frozenset[str] = frozenset({"1", "1.0"})

#: Face components whose ``install-harness`` is called during onboarding.
_FACE_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("agent-notes", "agent-notes"),
    ("cairn", "agent-provenance"),
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OnboardStepResult:
    """The outcome of one onboarding step."""

    step: OnboardStep
    status: OnboardStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class OnboardResult:
    """The full onboarding outcome.

    ``spec_anchored`` is True only when the spec was signed (or was already
    signed) as event-zero.  A project onboarded without a spec is valid but
    ``spec_anchored`` is False and the result says "spec-unanchored."

    ``spec_version_recognized`` is ``None`` when no spec was provided or no
    ``schema_version`` field was found; ``True``/``False`` when a version was
    extracted and checked against :data:`RECOGNIZED_SPEC_VERSIONS`.
    """

    ok: bool
    dry_run: bool
    project: str
    spec_anchored: bool
    spec_version: str | None
    spec_version_recognized: bool | None
    steps: list[OnboardStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "project": self.project,
            "spec_anchored": self.spec_anchored,
            "spec_version": self.spec_version,
            "spec_version_recognized": self.spec_version_recognized,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# Spec reading (stdlib-only; the spec is signed, not parsed)
# ---------------------------------------------------------------------------


def _extract_schema_version(text: str) -> str | None:
    """Extract the ``schema_version`` field from a YAML spec.

    Uses a simple line-based scan rather than a full YAML parser — the spec
    is *signed*, not *parsed* (Plan 025 WI-4.3: "Regista does not parse the
    spec; it stores and signs it").  We only need the schema version for
    interchange discipline (recording + recognising it).
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("schema_version:"):
            value = stripped[len("schema_version:"):].strip()
            # Strip surrounding quotes if present (YAML basic-string)
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            return value if value else None
    return None


def _compute_spec_md_hash(spec_path: Path) -> str | None:
    """Compute the SHA-256 hash of the sibling ``spec.md`` file, if it exists.

    The spec.md is the human-readable companion to the machine-readable
    spec.yaml.  Its hash is included in the signed event-zero so both the
    machine and human specs are anchored.
    """
    spec_md_path = spec_path.with_suffix(".md")
    try:
        return hashlib.sha256(spec_md_path.read_bytes()).hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _step_provision(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    project: str,
    principal: str | None = None,
) -> OnboardStepResult:
    if not installed("regista"):
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.FAILED,
            "regista CLI not installed — install regista before onboarding",
        )
    if dry_run:
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.PENDING,
            f"would provision project {project} (schema + service role + principal keys)",
        )

    prov_cmd: tuple[str, ...] = (
        "regista", "provision", "--project", project, "--json",
    )
    try:
        result = runner(prov_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.FAILED,
            f"provision failed: {exc}",
        )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "clobber" in stderr.lower() or "refuse" in stderr.lower():
            return OnboardStepResult(
                OnboardStep.PROVISION,
                OnboardStatus.REFUSED,
                f"provision refused (would clobber existing key/schema): {stderr}",
            )
        if "already" not in stderr.lower() and "exists" not in stderr.lower():
            return OnboardStepResult(
                OnboardStep.PROVISION,
                OnboardStatus.FAILED,
                f"provision failed: {stderr or 'no detail'}",
            )

    already_provisioned = False
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("schema_created") is False:
                already_provisioned = True
    elif isinstance(data, dict) and data.get("schema_created") is False:
        already_provisioned = True

    princ_id = principal or "suite-service"
    princ_cmd: tuple[str, ...] = (
        "regista", "provision-principal", "--project", project,
        "--principal", princ_id, "--json",
    )
    try:
        princ_result = runner(princ_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.FAILED,
            f"provision-principal failed: {exc}",
        )
    if princ_result.returncode != 0:
        p_stderr = princ_result.stderr.strip()
        if "clobber" in p_stderr.lower() or "refuse" in p_stderr.lower():
            return OnboardStepResult(
                OnboardStep.PROVISION,
                OnboardStatus.REFUSED,
                f"provision-principal refused (would clobber existing key for {princ_id}): {p_stderr}",
            )
        if "already" in p_stderr.lower() or "exists" in p_stderr.lower():
            already_provisioned = True
        else:
            return OnboardStepResult(
                OnboardStep.PROVISION,
                OnboardStatus.FAILED,
                f"provision-principal failed: {p_stderr or 'no detail'}",
            )

    status = OnboardStatus.ALREADY_DONE if already_provisioned else OnboardStatus.DONE
    return OnboardStepResult(
        OnboardStep.PROVISION, status,
        f"project {project} provisioned (principal: {princ_id})",
    )


def _step_sign_spec(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    project: str,
    spec_path: Path,
) -> OnboardStepResult:
    if not installed("regista"):
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            "regista CLI not installed — cannot sign spec",
        )
    if dry_run:
        md_note = " (+ spec.md hash)" if spec_path.with_suffix(".md").exists() else ""
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.PENDING,
            f"would sign {spec_path}{md_note} as event-zero for project {project}",
        )

    spec_md_hash = _compute_spec_md_hash(spec_path)

    sign_cmd: list[str] = [
        "regista", "spec", "sign",
        "--project", project,
        "--spec", str(spec_path),
    ]
    if spec_md_hash is not None:
        sign_cmd += ["--spec-md-hash", spec_md_hash]
    sign_cmd.append("--json")

    try:
        result = runner(tuple(sign_cmd))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"spec sign failed: {exc}",
        )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "already" in stderr.lower() or "exists" in stderr.lower():
            return OnboardStepResult(
                OnboardStep.SIGN_SPEC,
                OnboardStatus.ALREADY_DONE,
                f"spec already signed as event-zero for project {project}",
            )
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"spec sign failed: {stderr or 'no detail'}",
        )
    return OnboardStepResult(
        OnboardStep.SIGN_SPEC,
        OnboardStatus.DONE,
        f"spec signed as event-zero for project {project}",
    )


def _step_wire_harness(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    harness: str,
) -> OnboardStepResult:
    if dry_run:
        cmds = [
            f"{cli} install-harness --harness {harness}"
            for cli, _ in _FACE_COMPONENTS
        ]
        return OnboardStepResult(
            OnboardStep.WIRE_HARNESS,
            OnboardStatus.PENDING,
            f"would run: {'; '.join(cmds)}",
        )

    details: list[str] = []
    for cli_name, _ident in _FACE_COMPONENTS:
        if not installed(cli_name):
            return OnboardStepResult(
                OnboardStep.WIRE_HARNESS,
                OnboardStatus.FAILED,
                f"{cli_name} not installed — required for face wiring",
            )
        install_cmd: tuple[str, ...] = (cli_name, "install-harness", "--harness", harness)
        try:
            result = runner(install_cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return OnboardStepResult(
                OnboardStep.WIRE_HARNESS,
                OnboardStatus.FAILED,
                f"{cli_name} install-harness failed: {exc}",
            )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "already" in stderr.lower() or "no-op" in stderr.lower():
                details.append(f"{cli_name} already installed")
                continue
            return OnboardStepResult(
                OnboardStep.WIRE_HARNESS,
                OnboardStatus.FAILED,
                f"{cli_name} install-harness failed: {stderr or 'no detail'}",
            )
        details.append(f"{cli_name} installed")

    all_already = bool(details) and all("already" in d for d in details)
    status = OnboardStatus.ALREADY_DONE if all_already else OnboardStatus.DONE
    return OnboardStepResult(
        OnboardStep.WIRE_HARNESS, status, "; ".join(details),
    )


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def _is_terminal(status: OnboardStatus) -> bool:
    """A step that stops the pipeline (failure or refusal)."""
    match status:
        case OnboardStatus.FAILED | OnboardStatus.REFUSED:
            return True
        case (
            OnboardStatus.DONE
            | OnboardStatus.ALREADY_DONE
            | OnboardStatus.SKIPPED
            | OnboardStatus.PENDING
        ):
            return False
        case other:
            assert_never(other)


def _compute_ok(steps: list[OnboardStepResult]) -> bool:
    for s in steps:
        match s.status:
            case OnboardStatus.FAILED | OnboardStatus.REFUSED:
                return False
            case (
                OnboardStatus.DONE
                | OnboardStatus.ALREADY_DONE
                | OnboardStatus.SKIPPED
                | OnboardStatus.PENDING
            ):
                continue
            case other:
                assert_never(other)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_onboard(
    *,
    project: str,
    spec_path: Path | None = None,
    dry_run: bool = False,
    harness: str = "all",
    principal: str | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> OnboardResult:
    """Onboard a project: spec -> provision -> sign event-zero -> wire harness.

    Each step is gated on the prior step's success.  ``dry_run`` prints the
    plan without acting.  A step that would clobber an existing key or schema
    refuses.  Missing external dependencies fail with a named, actionable
    message.

    When ``spec_path`` is ``None`` the project is provisioned and
    harness-wired but no spec is signed — the project is "spec-unanchored"
    (valid, just without a founding spec in the audit chain).
    """
    steps: list[OnboardStepResult] = []
    spec_anchored = False
    spec_version: str | None = None
    spec_version_recognized: bool | None = None

    # --- Step 1: validate spec (if provided) ---
    if spec_path is not None:
        if dry_run:
            steps.append(OnboardStepResult(
                OnboardStep.VALIDATE_SPEC,
                OnboardStatus.PENDING,
                f"would validate spec at {spec_path}",
            ))
        else:
            try:
                text = spec_path.read_text(encoding="utf-8")
            except OSError as exc:
                steps.append(OnboardStepResult(
                    OnboardStep.VALIDATE_SPEC,
                    OnboardStatus.FAILED,
                    f"cannot read spec: {exc}",
                ))
                return OnboardResult(
                    ok=False, dry_run=dry_run, project=project,
                    spec_anchored=False, spec_version=None,
                    spec_version_recognized=None, steps=steps,
                )
            spec_version = _extract_schema_version(text)
            if spec_version is not None:
                spec_version_recognized = spec_version in RECOGNIZED_SPEC_VERSIONS
                if spec_version_recognized:
                    detail = f"spec validated (schema_version: {spec_version})"
                else:
                    detail = (
                        f"spec read but schema_version '{spec_version}' is not "
                        f"recognised (recognised: {sorted(RECOGNIZED_SPEC_VERSIONS)})"
                    )
            else:
                detail = "spec read; no schema_version field found"
                spec_version_recognized = None
            steps.append(OnboardStepResult(
                OnboardStep.VALIDATE_SPEC,
                OnboardStatus.DONE,
                detail,
            ))
    else:
        steps.append(OnboardStepResult(
            OnboardStep.VALIDATE_SPEC,
            OnboardStatus.SKIPPED,
            "no spec provided — project will be spec-unanchored",
        ))

    # --- Step 2: provision ---
    prov_result = _step_provision(
        runner=runner, installed=installed, dry_run=dry_run,
        project=project, principal=principal,
    )
    steps.append(prov_result)
    if _is_terminal(prov_result.status):
        return OnboardResult(
            ok=False, dry_run=dry_run, project=project,
            spec_anchored=False, spec_version=spec_version,
            spec_version_recognized=spec_version_recognized, steps=steps,
        )

    # --- Step 3: sign spec as event-zero (if spec provided) ---
    if spec_path is not None:
        sign_result = _step_sign_spec(
            runner=runner, installed=installed, dry_run=dry_run,
            project=project, spec_path=spec_path,
        )
        steps.append(sign_result)
        if _is_terminal(sign_result.status):
            return OnboardResult(
                ok=False, dry_run=dry_run, project=project,
                spec_anchored=False, spec_version=spec_version,
                spec_version_recognized=spec_version_recognized, steps=steps,
            )
        spec_anchored = sign_result.status in (OnboardStatus.DONE, OnboardStatus.ALREADY_DONE)
    else:
        steps.append(OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.SKIPPED,
            "no spec to sign — project is spec-unanchored",
        ))

    # --- Step 4: wire harness (dual-target) ---
    harness_result = _step_wire_harness(
        runner=runner, installed=installed, dry_run=dry_run, harness=harness,
    )
    steps.append(harness_result)
    if _is_terminal(harness_result.status):
        return OnboardResult(
            ok=False, dry_run=dry_run, project=project,
            spec_anchored=spec_anchored, spec_version=spec_version,
            spec_version_recognized=spec_version_recognized, steps=steps,
        )

    return OnboardResult(
        ok=_compute_ok(steps), dry_run=dry_run, project=project,
        spec_anchored=spec_anchored, spec_version=spec_version,
        spec_version_recognized=spec_version_recognized, steps=steps,
    )


def format_text(result: OnboardResult) -> str:
    """Human-readable summary for ``onboard`` without ``--json``."""
    lines: list[str] = []
    if result.dry_run:
        lines.append("agent-suite onboard --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite onboard")
    lines.append("")
    for s in result.steps:
        lines.append(f"  {s.step.value:<18} {s.status.value:<14} {s.detail}")
    lines.append("")
    if result.spec_anchored:
        lines.append(f"project {result.project}: spec-anchored (event-zero signed)")
    elif result.spec_version is not None:
        lines.append(f"project {result.project}: spec-unanchored (spec not signed)")
    else:
        lines.append(f"project {result.project}: spec-unanchored (no spec provided)")
    if result.spec_version is not None:
        rec = "recognised" if result.spec_version_recognized else "UNRECOGNISED"
        lines.append(f"  spec schema_version: {result.spec_version} ({rec})")
    lines.append("")
    lines.append(f"onboard: {'OK' if result.ok else 'NOT OK'}")
    return "\n".join(lines)
