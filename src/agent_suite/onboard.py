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
4. Wire the selected suite harness target (Claude, OpenCode, Codex, or the
   deterministic stable ``all`` set).

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

WI-053 — the sign step now calls a command that exists
------------------------------------------------------

``_step_sign_spec`` built ``regista spec sign --project X --spec P``. Every part
of that was wrong, so the feature had never worked on any host:

* ``--spec`` is not an option — the spec file is a **positional** argument, and
  ``--spec`` is in fact ambiguous against ``--spec-md-file`` / ``--spec-md-hash``
  / ``--spec-id``, so argparse rejected it before anything else was considered.
* ``--project`` is declared on regista's **top-level** parser, so it must precede
  the subcommand.
* ``--schema-version`` and ``--actor-id`` are **required** and were never passed.
* ``spec_md_hash`` must be non-empty — regista raises ``INVALID_ARGUMENT`` on a
  blank one — and this passed ``--spec-md-hash`` only when a sibling ``spec.md``
  happened to exist.

Lane H made the step fail honestly rather than possibly reporting
``already_done``; this makes it work. Verified against regista main
(``_cli.py`` ``spec_sign``, ``_api_meta.sign_spec``).

**Idempotency, and what a re-run does.** regista exposes no "already signed"
signal — no result flag and no error code meaning "this exact spec is already
event-zero" — and ``sign_spec`` generates a fresh random ``spec_id`` on every
call, so a naive re-run mints a *second, unrelated* spec entity. So the step
derives the entity id deterministically from the project slug
(:func:`spec_entity_id`) and asks ``regista spec events --spec-id …`` first:

* same project, same spec content already signed → ``ALREADY_DONE``, nothing
  written. This is the idempotency ``onboard`` promises.
* same project, **changed** spec content → a further ``spec_signed`` event on the
  *same* entity, and the step says the founding spec was amended. The chain then
  records both versions in order, which is the honest outcome for an amended
  spec and is what a random ``spec_id`` per run destroys.
* the pre-check itself failing is a failure, never an assumption that the spec is
  unsigned — signing again on a bad read is how a duplicate event-zero gets
  written.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.component_result import evaluate_component_result
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
# Injectable interfaces (same shape as bootstrap.Runner / doctor.Runner)
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

    ``None`` means there is no ``spec.md`` — which regista treats as a hard error
    (``sign_spec`` raises ``INVALID_ARGUMENT`` on an empty ``spec_md_hash``), so
    the step refuses rather than inventing a hash for a file that does not exist.
    """
    spec_md_path = spec_path.with_suffix(".md")
    try:
        return hashlib.sha256(spec_md_path.read_bytes()).hexdigest()
    except OSError:
        return None


#: Namespace for the derived spec entity id. Fixed forever: changing it would make
#: every already-onboarded project look unsigned and mint a duplicate event-zero.
_SPEC_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://agent-suite/spec-zero")


def spec_entity_id(project: str) -> uuid.UUID:
    """The project's founding-spec entity id, derived from its slug.

    regista's ``sign_spec`` generates a random ``spec_id`` when none is given, so
    two runs of ``onboard --spec`` produce two unrelated spec entities and there
    is no way to ask "is this project's spec already signed?" (WI-053). Deriving
    the id makes the question answerable — ``regista spec events --spec-id`` — and
    makes an amended spec a second event on the *same* entity rather than a
    second, competing event-zero.

    A project has exactly one founding-spec entity, so the slug is the whole
    input. Deriving from the spec *content* instead would give each edit its own
    entity, which is the same problem in a different shape.
    """
    return uuid.uuid5(_SPEC_ID_NAMESPACE, project)


def spec_sign_argv(
    *,
    project: str,
    spec_path: Path,
    schema_version: str,
    actor_id: str,
    spec_md_hash: str,
    spec_id: uuid.UUID,
) -> tuple[str, ...]:
    """Build ``regista spec sign`` as regista's parser actually defines it.

    ``--project`` is a top-level option so it precedes the subcommand; the spec
    file is a positional; ``--schema-version`` and ``--actor-id`` are required.
    """
    return (
        "regista",
        "--project",
        project,
        "spec",
        "sign",
        str(spec_path),
        "--schema-version",
        schema_version,
        "--actor-id",
        actor_id,
        "--spec-md-hash",
        spec_md_hash,
        "--spec-id",
        str(spec_id),
        "--json",
    )


def spec_events_argv(*, project: str, spec_id: uuid.UUID) -> tuple[str, ...]:
    """Build the idempotency pre-check: this project's spec events, if any.

    Filtered to the derived entity and bounded by regista's own ``--limit``, so
    the cost does not grow with the project's history (Plan 020's first standing
    question — ``onboard`` is not a health path, but an unbounded read on it is
    still a defect).
    """
    return (
        "regista",
        "--project",
        project,
        "spec",
        "events",
        "--spec-id",
        str(spec_id),
        "--limit",
        "50",
        "--json",
    )


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _provision_status_for(outcome: ProvisionOutcome) -> OnboardStatus:
    match outcome:
        case ProvisionOutcome.DONE:
            return OnboardStatus.DONE
        case ProvisionOutcome.ALREADY_DONE:
            return OnboardStatus.ALREADY_DONE
        case ProvisionOutcome.REFUSED:
            return OnboardStatus.REFUSED
        case ProvisionOutcome.FAILED:
            return OnboardStatus.FAILED
        case other:
            assert_never(other)


def _step_provision(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    project: str,
    principal: str | None = None,
) -> OnboardStepResult:
    """Provision the project and its principal (WI-040, WI-051).

    Both verdicts come from :mod:`agent_suite.provisioning`, which reads the
    child's structured result and classifies a refusal by its error code. The
    string-matching this used to do ("already"/"exists" in stderr means
    success) reported a hard integrity stop as a green step.
    """
    if not installed("regista"):
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.FAILED,
            "regista CLI not installed — install regista before onboarding",
        )
    princ_id = default_principal(principal)
    if dry_run:
        return OnboardStepResult(
            OnboardStep.PROVISION,
            OnboardStatus.PENDING,
            f"would provision project {project} (schema + service role + "
            f"principal keys for {princ_id})",
        )
    report = provision_projects(
        runner=runner, projects=(project,), principal=princ_id
    )
    return OnboardStepResult(
        OnboardStep.PROVISION,
        _provision_status_for(report.outcome),
        report.detail,
    )


def _already_signed(
    *,
    runner: Runner,
    project: str,
    spec_id: uuid.UUID,
    spec_md_hash: str,
    schema_version: str,
) -> tuple[bool, OnboardStepResult | None]:
    """Whether this exact spec is already this project's event-zero.

    regista offers no idempotent signal, so the suite constructs one from a
    bounded read of the derived entity's own events. A signed spec matches when
    both the ``spec_md_hash`` and the ``spec_schema_version`` recorded in the
    payload agree — those are the two fields ``sign_spec`` stores that identify
    *which* spec was signed (the ``spec_yaml`` is stored too, but comparing it
    would mean shipping the whole document through an argv-adjacent read).

    Returns ``(already_signed, failure)``. A pre-check that could not run is a
    **failure**, never "assume unsigned": signing on a bad read is precisely how
    a duplicate event-zero gets written.
    """
    argv = spec_events_argv(project=project, spec_id=spec_id)
    try:
        result = runner(argv)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"could not read existing spec events: {exc} — refusing to sign "
            f"without knowing whether {project} already has an event-zero",
        )
    if result.returncode != 0:
        return False, OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"regista spec events exited {result.returncode}: "
            f"{result.stderr.strip()[:300] or 'no detail'} — refusing to sign "
            f"without knowing whether {project} already has an event-zero",
        )
    try:
        events = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False, OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            "regista spec events --json emitted non-JSON — refusing to sign "
            "without knowing whether this project already has an event-zero",
        )
    if not isinstance(events, list):
        return False, OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"regista spec events --json returned {type(events).__name__}, "
            f"expected a list — refusing to sign on an unreadable result",
        )
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("spec_md_hash") == spec_md_hash
            and str(payload.get("spec_schema_version", "")) == schema_version
        ):
            return True, None
    return False, None


def _step_sign_spec(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    project: str,
    spec_path: Path,
    schema_version: str | None,
    principal: str | None = None,
) -> OnboardStepResult:
    """Sign the spec as the project's event-zero via ``regista spec sign``.

    See the module docstring for what a re-run does. Every required regista
    argument is now supplied, and each one that the suite cannot supply is a
    refusal that names the missing input rather than a call that fails obscurely.
    """
    if not installed("regista"):
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            "regista CLI not installed — cannot sign spec",
        )
    spec_md_path = spec_path.with_suffix(".md")
    if dry_run:
        md_note = " (+ spec.md hash)" if spec_md_path.exists() else ""
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.PENDING,
            f"would sign {spec_path}{md_note} as event-zero for project {project} "
            f"(spec entity {spec_entity_id(project)})",
        )

    # regista requires --schema-version; the suite reads it out of the spec in
    # step 1. Without it there is nothing to pass, and inventing a default would
    # sign a version claim the spec does not make.
    if not schema_version:
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.REFUSED,
            f"{spec_path} declares no 'schema_version', which "
            f"'regista spec sign' requires — add one (recognised: "
            f"{sorted(RECOGNIZED_SPEC_VERSIONS)}) and re-run",
        )

    # regista raises INVALID_ARGUMENT on an empty spec_md_hash, so the human
    # companion document is mandatory, not optional. Refuse and say which file.
    spec_md_hash = _compute_spec_md_hash(spec_path)
    if spec_md_hash is None:
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.REFUSED,
            f"'regista spec sign' requires a spec.md hash and {spec_md_path} does "
            f"not exist — the signed event-zero anchors both the machine-readable "
            f"and human-readable spec, so create it and re-run",
        )

    # The actor is the principal step 2 provisioned a key for. regista binds each
    # key to a principal and rejects any event whose actor_id differs from its
    # key's principal_id, so this must be that same id (see provisioning.py).
    actor_id = default_principal(principal)
    spec_id = spec_entity_id(project)

    already, failure = _already_signed(
        runner=runner,
        project=project,
        spec_id=spec_id,
        spec_md_hash=spec_md_hash,
        schema_version=schema_version,
    )
    if failure is not None:
        return failure
    if already:
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.ALREADY_DONE,
            f"spec {spec_path} is already event-zero for {project} "
            f"(spec entity {spec_id}, schema_version {schema_version})",
        )

    sign_cmd = spec_sign_argv(
        project=project,
        spec_path=spec_path,
        schema_version=schema_version,
        actor_id=actor_id,
        spec_md_hash=spec_md_hash,
        spec_id=spec_id,
    )
    try:
        result = runner(sign_cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"spec sign failed: {exc}",
        )
    verdict = evaluate_component_result(
        command=f"regista --project {project} spec sign",
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if not verdict.ok:
        # Still no "already signed" branch on the *failure* path: regista has no
        # code meaning "this exact spec is already event-zero", and the old
        # "already"/"exists" substring match reported any failure whose message
        # happened to contain those words as a completed step. Idempotency is
        # established before the write, by reading the chain — not inferred
        # afterwards from prose.
        return OnboardStepResult(
            OnboardStep.SIGN_SPEC,
            OnboardStatus.FAILED,
            f"spec sign failed: {verdict.detail}",
        )
    return OnboardStepResult(
        OnboardStep.SIGN_SPEC,
        OnboardStatus.DONE,
        f"spec signed as event-zero for project {project} "
        f"(spec entity {spec_id}, actor {actor_id}, "
        f"schema_version {schema_version})",
    )


def _step_wire_harness(
    *,
    runner: Runner,
    installed: Installed,
    dry_run: bool,
    harness: HarnessTarget,
) -> OnboardStepResult:
    targets = expand_harness_target(harness)
    if dry_run:
        cmds = [
            " ".join(install_harness_argv(cli, target))
            for cli, _ in _FACE_COMPONENTS
            for target in targets
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
        for target in targets:
            install_cmd = install_harness_argv(cli_name, target)
            try:
                result = runner(install_cmd)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                return OnboardStepResult(
                    OnboardStep.WIRE_HARNESS,
                    OnboardStatus.FAILED,
                    f"{cli_name} install-harness failed: {exc}",
                )
            evaluation = evaluate_install_harness_result(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                expected_tool=cli_name,
                expected_harness=target,
                require_structured=requires_structured_install_result(cli_name),
            )
            if not evaluation.ok:
                return OnboardStepResult(
                    OnboardStep.WIRE_HARNESS,
                    OnboardStatus.FAILED,
                    f"{cli_name} install-harness {target.value} "
                    f"{evaluation.status.value}: {evaluation.detail}",
                )
            state = "already installed" if evaluation.no_op else "installed"
            details.append(f"{cli_name} {target.value} {state}")

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
    harness: HarnessTarget = HarnessTarget.ALL,
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
    harness = normalize_harness_target(harness)
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
            schema_version=spec_version, principal=principal,
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

    # --- Step 4: wire the selected stable suite harness target ---
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
