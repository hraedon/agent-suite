"""Per-user identity lifecycle — onboarding and offboarding (Plan 001 WI-3.3).

``docs/multi-user-onboarding.md`` §3 specifies joining (write a per-user
``suite.env`` overlay + provision the principal's signing key) and §6
specifies leaving (revoke the principal's keys, then remove the private key
from the secret backend). The documented contract existed; the code did not —
bootstrap step 7 reported "not yet implemented" and there was no leaver path
at all.

Design (AGENTS.md): thin orchestration. Every irreversible act is regista's
own CLI verb (``regista principal enroll`` / ``list`` / ``revoke``); this
module owns only the ordering, the overlay file, and honest reporting. The
runner and installed-check are injectable (the ``doctor.py`` / ``bootstrap.py``
pattern) so tests drive the full lifecycle against a stubbed regista with no
live store.

Offboarding revokes the key (the SLA-bearing act, which windows it out of the
registry) *and* deletes the custodied private key, so the fetch path closes
too. Where deletion is genuinely impossible — a backend that refuses, or a
reference that carries the secret inline rather than pointing at it — the run
reports ``MANUAL`` with the exact refs, never folding it into success.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, assert_never

from agent_suite.config import user_suite_env_path, _parse_env_file


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as bootstrap.Runner / bootstrap.Installed)
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


class IdentityAction(Enum):
    """Which half of the lifecycle ran."""

    ONBOARD = "onboard"
    OFFBOARD = "offboard"


class IdentityOutcome(Enum):
    """The outcome of one step, and of the run as a whole.

    ``MANUAL`` is the honest seam: the suite did everything it can do and an
    operator action remains. It is distinct from ``DONE`` so that automation
    cannot read a half-finished offboarding as complete.
    """

    DONE = "done"
    ALREADY_DONE = "already_done"
    PENDING = "pending"
    MANUAL = "manual_action_required"
    REFUSED = "refused"
    FAILED = "failed"


# Worst-first: the aggregate outcome is the first of these any step reports.
_OUTCOME_PRECEDENCE: tuple[IdentityOutcome, ...] = (
    IdentityOutcome.FAILED,
    IdentityOutcome.REFUSED,
    IdentityOutcome.MANUAL,
    IdentityOutcome.PENDING,
    IdentityOutcome.DONE,
    IdentityOutcome.ALREADY_DONE,
)


def outcome_is_success(outcome: IdentityOutcome) -> bool:
    """True when the outcome needs no further action to be correct."""
    match outcome:
        case IdentityOutcome.DONE | IdentityOutcome.ALREADY_DONE | IdentityOutcome.PENDING:
            return True
        case IdentityOutcome.MANUAL | IdentityOutcome.REFUSED | IdentityOutcome.FAILED:
            return False
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityStep:
    """One step of the lifecycle."""

    name: str
    outcome: IdentityOutcome
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IdentityResult:
    """The whole run: every step, plus the worst outcome among them."""

    action: IdentityAction
    principal: str
    outcome: IdentityOutcome
    steps: tuple[IdentityStep, ...]

    @property
    def ok(self) -> bool:
        return outcome_is_success(self.outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action.value,
            "principal": self.principal,
            "outcome": self.outcome.value,
            "steps": [s.to_dict() for s in self.steps],
        }


def aggregate_outcome(steps: tuple[IdentityStep, ...]) -> IdentityOutcome:
    """Reduce step outcomes to one, worst-first."""
    if not steps:
        return IdentityOutcome.ALREADY_DONE
    reported = {s.outcome for s in steps}
    for candidate in _OUTCOME_PRECEDENCE:
        if candidate in reported:
            return candidate
    raise AssertionError(f"unreduced outcomes: {reported}")


# ---------------------------------------------------------------------------
# The per-user suite.env overlay (bootstrap-contract §2, onboarding doc §3)
# ---------------------------------------------------------------------------


_OVERLAY_HEADER = (
    "# Per-user overlay — written by `agent-suite bootstrap --user <principal>`.\n"
    "# Layers on top of the system suite.env; process env still wins.\n"
    "# Shared facts (DSN, secret backend) stay in the system file.\n"
)

PRINCIPAL_KEY = "REGISTA_PRINCIPAL_ID"
PROJECT_KEY = "AGENT_NOTES_PROJECT"
PROJECTS_KEY = "DOSSIER_PROJECTS"


def overlay_values(
    principal: str,
    *,
    project: str | None = None,
    projects: tuple[str, ...] = (),
) -> dict[str, str]:
    """The keys this suite owns in a per-user overlay."""
    values = {PRINCIPAL_KEY: principal}
    if project:
        values[PROJECT_KEY] = project
    if projects:
        values[PROJECTS_KEY] = ",".join(projects)
    return values


def render_overlay(values: dict[str, str]) -> str:
    """Render an overlay file body — stable order, so re-runs are no-ops."""
    lines = [_OVERLAY_HEADER]
    lines.extend(f"{key}={values[key]}\n" for key in sorted(values))
    return "".join(lines)


def write_overlay(
    path: Path,
    values: dict[str, str],
    *,
    dry_run: bool = False,
) -> IdentityStep:
    """Merge ``values`` into the overlay at ``path``.

    Keys the suite does not own are preserved. Re-running with the same inputs
    rewrites byte-identical content and reports ``ALREADY_DONE``, so the step
    is idempotent in the sense the bootstrap contract requires.
    """
    existing = _parse_env_file(path)
    merged = {**existing, **values}
    body = render_overlay(merged)
    if path.is_file() and path.read_text(encoding="utf-8") == body:
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.ALREADY_DONE,
            f"overlay at {path} already current",
        )
    if dry_run:
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.PENDING,
            f"would write overlay at {path} ({', '.join(sorted(values))})",
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError as exc:
        return IdentityStep(
            "user_overlay", IdentityOutcome.FAILED, f"could not write {path}: {exc}"
        )
    return IdentityStep(
        "user_overlay", IdentityOutcome.DONE, f"overlay written at {path}"
    )


def remove_overlay(path: Path, *, dry_run: bool = False) -> IdentityStep:
    """Delete a per-user overlay (leaver path)."""
    if not path.is_file():
        return IdentityStep(
            "user_overlay",
            IdentityOutcome.ALREADY_DONE,
            f"no overlay at {path}",
        )
    if dry_run:
        return IdentityStep(
            "user_overlay", IdentityOutcome.PENDING, f"would remove overlay at {path}"
        )
    try:
        path.unlink()
    except OSError as exc:
        return IdentityStep(
            "user_overlay", IdentityOutcome.FAILED, f"could not remove {path}: {exc}"
        )
    return IdentityStep(
        "user_overlay", IdentityOutcome.DONE, f"overlay removed at {path}"
    )


# ---------------------------------------------------------------------------
# regista principal verbs
# ---------------------------------------------------------------------------


def _run_regista(
    runner: Runner, cmd: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str] | None, str]:
    """Run a regista command; return (result, error-detail-if-it-could-not-run)."""
    try:
        return runner(cmd), ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, str(exc)


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _enroll_principal(
    *,
    runner: Runner,
    principal: str,
    secret_backend: str | None,
    dry_run: bool,
) -> IdentityStep:
    cmd: tuple[str, ...] = ("regista", "principal", "enroll", "--principal", principal)
    if secret_backend:
        cmd += ("--secret-backend", secret_backend)
    cmd += ("--json",)
    if dry_run:
        return IdentityStep(
            "principal_key",
            IdentityOutcome.PENDING,
            f"would run {' '.join(cmd)}",
        )
    result, run_error = _run_regista(runner, cmd)
    if result is None:
        return IdentityStep(
            "principal_key", IdentityOutcome.FAILED, f"enroll failed: {run_error}"
        )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # regista refuses rather than overwriting an existing key — surface
        # that as REFUSED, not FAILED: nothing is wrong, nothing was clobbered.
        if "clobber" in stderr.lower() or "refuse" in stderr.lower():
            return IdentityStep(
                "principal_key",
                IdentityOutcome.REFUSED,
                f"enroll refused (would clobber an existing key): {stderr}",
            )
        return IdentityStep(
            "principal_key",
            IdentityOutcome.FAILED,
            f"enroll failed: {stderr or 'no detail'}",
        )
    data = _parse_json(result.stdout)
    if not isinstance(data, dict):
        return IdentityStep(
            "principal_key",
            IdentityOutcome.FAILED,
            "enroll --json emitted no JSON object on stdout",
        )
    key_id = data.get("key_id", "unknown")
    backend = data.get("secret_backend", "unknown")
    if data.get("already_existed") is True:
        return IdentityStep(
            "principal_key",
            IdentityOutcome.ALREADY_DONE,
            f"principal {principal} already has active key {key_id} ({backend})",
        )
    return IdentityStep(
        "principal_key",
        IdentityOutcome.DONE,
        f"enrolled key {key_id} for {principal} in {backend}",
    )


def _active_keys(
    *, runner: Runner, principal: str
) -> tuple[list[dict[str, Any]], IdentityStep | None]:
    """List a principal's active keys. Returns (keys, failure-step-or-None)."""
    cmd: tuple[str, ...] = (
        "regista", "principal", "list",
        "--principal", principal,
        "--status", "active",
        "--json",
    )
    result, run_error = _run_regista(runner, cmd)
    if result is None:
        return [], IdentityStep(
            "revoke_keys", IdentityOutcome.FAILED, f"principal list failed: {run_error}"
        )
    if result.returncode != 0:
        return [], IdentityStep(
            "revoke_keys",
            IdentityOutcome.FAILED,
            f"principal list failed: {result.stderr.strip() or 'no detail'}",
        )
    data = _parse_json(result.stdout)
    if not isinstance(data, list):
        return [], IdentityStep(
            "revoke_keys",
            IdentityOutcome.FAILED,
            "principal list --json emitted no JSON array on stdout",
        )
    return [entry for entry in data if isinstance(entry, dict)], None


def _revoke_keys(
    *,
    runner: Runner,
    principal: str,
    reason: str,
    dry_run: bool,
) -> tuple[IdentityStep, list[dict[str, Any]]]:
    """Revoke every active key for ``principal``. Returns (step, revoked-entries)."""
    keys, failure = _active_keys(runner=runner, principal=principal)
    if failure is not None:
        return failure, []
    if not keys:
        return (
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.ALREADY_DONE,
                f"principal {principal} has no active keys",
            ),
            [],
        )
    key_ids = [str(k.get("key_id", "")) for k in keys if k.get("key_id")]
    if dry_run:
        return (
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.PENDING,
                f"would revoke {len(key_ids)} active key(s): {', '.join(key_ids)}",
            ),
            keys,
        )
    revoked: list[dict[str, Any]] = []
    for entry, key_id in zip(keys, key_ids, strict=True):
        cmd: tuple[str, ...] = (
            "regista", "principal", "revoke",
            "--principal", principal,
            "--key-id", key_id,
            "--reason", reason,
            "--json",
        )
        result, run_error = _run_regista(runner, cmd)
        if result is None or result.returncode != 0:
            detail = run_error or (result.stderr.strip() if result else "")
            # Report what did land — a half-revoked principal is exactly the
            # state an operator must not mistake for a clean offboarding.
            return (
                IdentityStep(
                    "revoke_keys",
                    IdentityOutcome.FAILED,
                    f"revoked {len(revoked)}/{len(key_ids)} keys; "
                    f"{key_id} failed: {detail or 'no detail'}",
                ),
                revoked,
            )
        revoked.append(entry)
    return (
        IdentityStep(
            "revoke_keys",
            IdentityOutcome.DONE,
            f"revoked {len(revoked)} key(s): {', '.join(key_ids)}",
        ),
        revoked,
    )


def _secret_backend_step(
    revoked: list[dict[str, Any]],
    *,
    runner: Runner,
    dry_run: bool,
) -> IdentityStep:
    """Remove the custodied private keys, so the fetch path actually closes.

    Revocation windows the key out of the registry (onboarding doc §6) but
    leaves the private key readable from the backend; deleting it is what
    finishes the job. ``regista secrets --delete`` is idempotent, so a re-run
    of an offboarding is safe.

    Two outcomes are not deletions and are reported as ``MANUAL`` rather than
    folded into success: a backend that refuses (``env:``), and a reference
    that *carries* the secret rather than pointing at it (``windows:``,
    ``literal:``) — there the operator has to discard the reference itself,
    because every copy of it is a copy of the key.
    """
    refs = sorted(
        {
            str(entry["secret_ref"])
            for entry in revoked
            if isinstance(entry.get("secret_ref"), str) and entry["secret_ref"]
        }
    )
    if not refs:
        return IdentityStep(
            "secret_backend",
            IdentityOutcome.ALREADY_DONE,
            "no custodied private-key refs recorded for the revoked keys",
        )
    if dry_run:
        return IdentityStep(
            "secret_backend",
            IdentityOutcome.PENDING,
            f"would delete {len(refs)} custodied private key(s): {', '.join(refs)}",
        )

    deleted: list[str] = []
    inline: list[str] = []
    failed: list[str] = []
    for ref in refs:
        cmd: tuple[str, ...] = ("regista", "--json", "secrets", "--ref", ref, "--delete")
        result, run_error = _run_regista(runner, cmd)
        if result is None or result.returncode != 0:
            failed.append(f"{ref} ({run_error or 'delete refused'})")
            continue
        data = _parse_json(result.stdout)
        outcome = data.get("outcome") if isinstance(data, dict) else None
        if outcome in ("deleted", "already_absent"):
            deleted.append(ref)
        else:
            inline.append(ref)

    parts: list[str] = []
    if deleted:
        parts.append(f"deleted {len(deleted)} custodied key(s)")
    if inline:
        parts.append(
            f"{len(inline)} reference(s) carry the key inline and must be "
            f"discarded wherever they are recorded: {', '.join(inline)}"
        )
    if failed:
        parts.append(f"could not delete: {', '.join(failed)}")

    if failed or inline:
        return IdentityStep(
            "secret_backend", IdentityOutcome.MANUAL, "; ".join(parts)
        )
    return IdentityStep("secret_backend", IdentityOutcome.DONE, "; ".join(parts))


# ---------------------------------------------------------------------------
# The two lifecycle entry points
# ---------------------------------------------------------------------------


def run_user_onboarding(
    *,
    principal: str,
    project: str | None = None,
    projects: tuple[str, ...] = (),
    overlay_path: Path | None = None,
    secret_backend: str | None = None,
    dry_run: bool = False,
    runner: Runner | None = None,
    installed: Installed | None = None,
) -> IdentityResult:
    """Onboard one human or agent principal (onboarding doc §3).

    Writes the per-user overlay, then enrolls the principal's signing key.
    Both steps are idempotent; the key step never overwrites an existing key.
    """
    run = runner or _default_runner
    is_installed = installed or _default_installed
    path = overlay_path or user_suite_env_path()

    steps: list[IdentityStep] = [
        write_overlay(
            path,
            overlay_values(principal, project=project, projects=projects),
            dry_run=dry_run,
        )
    ]

    if not is_installed("regista"):
        steps.append(
            IdentityStep(
                "principal_key",
                IdentityOutcome.FAILED,
                "regista not installed — cannot provision the principal's signing key",
            )
        )
    else:
        steps.append(
            _enroll_principal(
                runner=run,
                principal=principal,
                secret_backend=secret_backend,
                dry_run=dry_run,
            )
        )

    frozen = tuple(steps)
    return IdentityResult(
        action=IdentityAction.ONBOARD,
        principal=principal,
        outcome=aggregate_outcome(frozen),
        steps=frozen,
    )


def run_user_offboarding(
    *,
    principal: str,
    reason: str = "offboarded",
    overlay_path: Path | None = None,
    keep_overlay: bool = False,
    dry_run: bool = False,
    runner: Runner | None = None,
    installed: Installed | None = None,
) -> IdentityResult:
    """Offboard one principal — the leaver process (onboarding doc §6).

    Revokes every active key, reports the secret-backend refs still to be
    removed, and (unless ``keep_overlay``) removes the per-user overlay.
    """
    run = runner or _default_runner
    is_installed = installed or _default_installed
    path = overlay_path or user_suite_env_path()

    steps: list[IdentityStep] = []
    if not is_installed("regista"):
        steps.append(
            IdentityStep(
                "revoke_keys",
                IdentityOutcome.FAILED,
                "regista not installed — cannot revoke the principal's keys",
            )
        )
    else:
        revoke_step, revoked = _revoke_keys(
            runner=run, principal=principal, reason=reason, dry_run=dry_run
        )
        steps.append(revoke_step)
        if revoke_step.outcome is not IdentityOutcome.FAILED:
            steps.append(
                _secret_backend_step(revoked, runner=run, dry_run=dry_run)
            )

    if keep_overlay:
        steps.append(
            IdentityStep(
                "user_overlay",
                IdentityOutcome.ALREADY_DONE,
                f"overlay at {path} left in place (--keep-overlay)",
            )
        )
    else:
        steps.append(remove_overlay(path, dry_run=dry_run))

    frozen = tuple(steps)
    return IdentityResult(
        action=IdentityAction.OFFBOARD,
        principal=principal,
        outcome=aggregate_outcome(frozen),
        steps=frozen,
    )


def format_result(result: IdentityResult) -> str:
    """Human-readable rendering (the non-``--json`` CLI path)."""
    lines = [f"{result.action.value} {result.principal}: {result.outcome.value}"]
    lines.extend(
        f"  {step.name:16s} {step.outcome.value:22s} {step.detail}"
        for step in result.steps
    )
    return "\n".join(lines)
