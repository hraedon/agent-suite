"""The provision step, once — shared by ``bootstrap`` and ``onboard``.

`bootstrap.py` and `onboard.py` each carried their own copy of "run `regista
provision`, then `regista provision-principal`, then decide what happened", and
both copies decided it by scanning the child's prose (WI-040, WI-051). Fixing
that in two places is how it comes back, so the decision lives here and both
callers ask this module.

Three behaviours this module is responsible for:

1. **Success comes from the structured envelope** — every verdict is
   :func:`~agent_suite.component_result.evaluate_component_result`, so a child
   that exits 0 with an ``error`` body fails the step (WI-040).

2. **A principal is one key, registered in each project it acts in.** regista
   WI-223 refuses to mint a second keypair for a principal that already has a
   signable one, because `keys.json` is shared across projects while
   `principal_keys` is per-project: the second mint demoted the first key and
   the signer — which selects by ``principal_id`` with no project scoping —
   started signing the *first* project's events with a key only the second
   project had registered. The refusal is correct and the fix is
   ``--reuse-existing-key``, which registers the existing public key in the
   additional project without minting or touching the key file. `suite-service`
   spans every project on a host, so reuse is the suite's normal path, not an
   exception (see :data:`REUSE_RATIONALE`).

3. **``already_done`` needs evidence.** The qualification run saw
   ``provision already_done`` on the *first* bootstrap of a clean host. A step
   is only already-done when the child affirmatively reports the work was
   already present — ``schema_created: false`` with no error (regista checked
   ``information_schema.schemata``), or ``already_existed: true`` — never
   because nothing bad was said.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, assert_never

from agent_suite.component_result import (
    ChildOutcome,
    ComponentResult,
    evaluate_component_result,
)

__all__ = [
    "PRINCIPAL_RESULT_FIELDS",
    "PROJECT_RESULT_FIELDS",
    "REUSE_RATIONALE",
    "ProvisionOutcome",
    "ProvisionReport",
    "default_principal",
    "provision_principal",
    "provision_project",
    "provision_projects",
]

#: Why the suite passes ``--reuse-existing-key`` rather than giving each project
#: its own key file. Kept as one string so the step detail, the docs, and the
#: tests cannot drift.
REUSE_RATIONALE = (
    "one principal, one key, registered in every project it acts in — the suite "
    "runs a single REGISTA_KEY_PATH per host, so a second keypair for the same "
    "principal would demote the first and leave the other project's chain signed "
    "by a key it never registered (regista WI-223)"
)

#: The name the suite provisions when no principal is given. It acts in every
#: project on the host, which is precisely why it needs key reuse.
_DEFAULT_PRINCIPAL = "suite-service"

#: Fields of ``regista provision``'s result the suite reads to judge the step.
#: Absence of any of them is a failure, not a pass.
PROJECT_RESULT_FIELDS: tuple[str, ...] = (
    "project",
    "schema_created",
    "service_role_created",
    "migrations_applied",
    "error",
)

#: Fields of ``regista provision-principal``'s result, likewise.
PRINCIPAL_RESULT_FIELDS: tuple[str, ...] = (
    "principal_id",
    "project",
    "key_id",
    "already_existed",
    "public_key_registered",
    "error",
)


class Runner(Protocol):
    """Run a component CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class ProvisionOutcome(StrEnum):
    """What provisioning did.

    Mapped onto the caller's own step-status enum, so bootstrap and onboard
    report the same facts under their own vocabularies.
    """

    DONE = "done"
    ALREADY_DONE = "already_done"
    REFUSED = "refused"
    FAILED = "failed"


#: Worst-first: the aggregate outcome of provisioning several projects.
_OUTCOME_PRECEDENCE: tuple[ProvisionOutcome, ...] = (
    ProvisionOutcome.FAILED,
    ProvisionOutcome.REFUSED,
    ProvisionOutcome.DONE,
    ProvisionOutcome.ALREADY_DONE,
)


@dataclass(frozen=True)
class ProvisionReport:
    """The outcome of provisioning, plus what it verified."""

    outcome: ProvisionOutcome
    detail: str

    @property
    def ok(self) -> bool:
        match self.outcome:
            case ProvisionOutcome.DONE | ProvisionOutcome.ALREADY_DONE:
                return True
            case ProvisionOutcome.REFUSED | ProvisionOutcome.FAILED:
                return False
            case other:
                assert_never(other)


def default_principal(principal: str | None = None) -> str:
    return principal or _DEFAULT_PRINCIPAL


def _outcome_for(result: ComponentResult) -> ProvisionOutcome:
    """Map a child verdict onto a provisioning outcome.

    Note what is *not* here: no branch on message text, and no branch that turns
    an unrecognised failure into a success. An error code the suite does not
    know is a failure (WI-051).
    """
    match result.outcome:
        case ChildOutcome.REFUSED:
            return ProvisionOutcome.REFUSED
        case ChildOutcome.FAILED:
            return ProvisionOutcome.FAILED
        case ChildOutcome.SUCCESS:
            raise AssertionError("success is interpreted by the caller, not mapped")
        case other:
            assert_never(other)


def _run(
    runner: Runner, cmd: tuple[str, ...], label: str
) -> tuple[ComponentResult | None, ProvisionReport | None]:
    """Run a child and evaluate it, or report why it could not run."""
    try:
        completed = runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, ProvisionReport(
            ProvisionOutcome.FAILED, f"{label} could not run: {exc}"
        )
    fields = (
        PROJECT_RESULT_FIELDS
        if cmd[1] == "provision"
        else PRINCIPAL_RESULT_FIELDS
    )
    return (
        evaluate_component_result(
            command=label,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            require_fields=fields,
        ),
        None,
    )


def provision_project(*, runner: Runner, project: str) -> ProvisionReport:
    """Create the project schema, run its migrations, create its service role.

    ``already_done`` requires the child to report that *nothing* was created and
    no migration was applied — the affirmative "it was already here" — rather
    than merely declining to complain.
    """
    label = f"regista provision --project {project}"
    cmd: tuple[str, ...] = ("regista", "provision", "--project", project, "--json")
    result, failure = _run(runner, cmd, label)
    if failure is not None:
        return failure
    assert result is not None
    if not result.ok:
        return ProvisionReport(_outcome_for(result), result.detail)

    created: list[str] = []
    for record in result.records:
        if record["schema_created"] is True:
            created.append("schema created")
        if record["migrations_applied"]:
            created.append(f"{len(record['migrations_applied'])} migration(s) applied")
        if record["service_role_created"] is True:
            created.append("service role created")
    if created:
        return ProvisionReport(
            ProvisionOutcome.DONE, f"{project}: {', '.join(created)}"
        )
    return ProvisionReport(
        ProvisionOutcome.ALREADY_DONE,
        f"{project}: schema, migrations and service role already present",
    )


def provision_principal(
    *,
    runner: Runner,
    project: str,
    principal: str,
    reuse_existing_key: bool = True,
) -> ProvisionReport:
    """Give ``principal`` a signable key registered in ``project``.

    On the refusal regista raises when the principal already holds a key in the
    shared key file (``PRINCIPAL_KEY_ALREADY_EXISTS``), this retries with
    ``--reuse-existing-key`` when ``reuse_existing_key`` is set, which registers
    the *existing* public key in this project. That is what multi-project
    onboarding of one principal means; without it, bootstrapping a host with two
    project slugs stops with REFUSED.

    The refusal is recognised by its **code**. Nothing here reads the child's
    message, so regista is free to reword it.
    """
    label = f"regista provision-principal --project {project} --principal {principal}"
    base: tuple[str, ...] = (
        "regista",
        "provision-principal",
        "--project",
        project,
        "--principal",
        principal,
        "--json",
    )
    result, failure = _run(runner, base, label)
    if failure is not None:
        return failure
    assert result is not None

    if result.outcome is ChildOutcome.REFUSED and result.code in {
        "PRINCIPAL_KEY_ALREADY_EXISTS"
    }:
        if not reuse_existing_key:
            return ProvisionReport(
                ProvisionOutcome.REFUSED,
                f"{result.detail} — pass reuse_existing_key to register the "
                f"principal's existing key in {project} ({REUSE_RATIONALE})",
            )
        reuse_label = f"{label} --reuse-existing-key"
        reuse_result, reuse_failure = _run(
            runner, (*base, "--reuse-existing-key"), reuse_label
        )
        if reuse_failure is not None:
            return reuse_failure
        assert reuse_result is not None
        if not reuse_result.ok:
            return ProvisionReport(_outcome_for(reuse_result), reuse_result.detail)
        return _interpret_principal(
            reuse_result, project=project, principal=principal, reused=True
        )

    if not result.ok:
        return ProvisionReport(_outcome_for(result), result.detail)
    return _interpret_principal(
        result, project=project, principal=principal, reused=False
    )


def _interpret_principal(
    result: ComponentResult,
    *,
    project: str,
    principal: str,
    reused: bool,
) -> ProvisionReport:
    """Turn a successful ``provision-principal`` result into a verdict.

    The success path is still checked: a result that reports neither an existing
    active key nor a newly registered public key has not given this project a
    signable identity, whatever its exit code was.
    """
    record = result.records[0] if len(result.records) == 1 else None
    if record is None:
        return ProvisionReport(
            ProvisionOutcome.FAILED,
            f"regista provision-principal returned {len(result.records)} records "
            f"for one principal; cannot tell what happened",
        )
    key_id = record["key_id"]
    if record["already_existed"] is True:
        return ProvisionReport(
            ProvisionOutcome.ALREADY_DONE,
            f"{principal} already has active key {key_id} in {project}",
        )
    if record["public_key_registered"] is not True:
        return ProvisionReport(
            ProvisionOutcome.FAILED,
            f"regista provision-principal reported neither an existing key nor a "
            f"registered one for {principal} in {project} "
            f"(already_existed=False, public_key_registered="
            f"{record['public_key_registered']!r}) — nothing signs for this "
            f"principal here",
        )
    if reused:
        return ProvisionReport(
            ProvisionOutcome.DONE,
            f"{principal}: existing key {key_id} registered in {project} "
            f"(--reuse-existing-key; {REUSE_RATIONALE})",
        )
    return ProvisionReport(
        ProvisionOutcome.DONE,
        f"{principal}: key {key_id} minted and registered in {project}",
    )


def provision_projects(
    *,
    runner: Runner,
    projects: Sequence[str],
    principal: str | None = None,
    reuse_existing_key: bool = True,
) -> ProvisionReport:
    """Provision every project slug the resolved config names (WI-042).

    ``suite.env.example`` ships ``CAIRN_PROJECT=agent_provenance`` — a different
    slug from ``REGISTA_PROJECT`` — and nothing provisioned it, so cairn was red
    after a by-the-book bootstrap that printed ``bootstrap: OK``. Provisioning
    stops at the first project that fails or is refused rather than pressing on
    into a half-provisioned estate.
    """
    if not projects:
        return ProvisionReport(
            ProvisionOutcome.FAILED,
            "no project configured — set REGISTA_PROJECT in suite.env",
        )
    princ = default_principal(principal)
    outcomes: list[ProvisionOutcome] = []
    details: list[str] = []
    for project in projects:
        for report in (
            provision_project(runner=runner, project=project),
            provision_principal(
                runner=runner,
                project=project,
                principal=princ,
                reuse_existing_key=reuse_existing_key,
            ),
        ):
            outcomes.append(report.outcome)
            details.append(report.detail)
            if not report.ok:
                return ProvisionReport(report.outcome, "; ".join(details))
    for candidate in _OUTCOME_PRECEDENCE:
        if candidate in outcomes:
            return ProvisionReport(candidate, "; ".join(details))
    raise AssertionError(f"unreduced provisioning outcomes: {outcomes}")
