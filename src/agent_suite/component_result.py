"""Decide a child CLI's outcome from its structured envelope, never its exit code.

WI-040. The Linux qualification found `bootstrap: OK` printed over a provision
that never created the service role: `regista provision --json` **exits 0** while
its JSON body carries ``{"error": "permission denied to create role",
"service_role_created": false}``. `docs/bootstrap-contract.md` §1 stops the
pipeline on "non-zero, malformed JSON, degraded, unsupported, failed" — a zero
exit whose body reports an error is none of those, so the step was accepted, and
then labelled ``already_done`` on the first bootstrap of a clean host.

WI-051 found the mirror-image defect: `_step_provision` classified a *failed*
`provision-principal` by substring-matching the child's prose, treating
``"already"``/``"exists"`` as success. regista had to word a hard integrity
refusal to lead with "Refusing to…" purely so this parser would not read it as a
green step — a component pinning its prose to satisfy a downstream string match.

Both are the same defect: **a step that did not succeed being read as success.**
So this module owns the one decision both bootstrap and onboard need, and it
makes it from facts the child asserts:

* an error envelope (`docs/cli-contract.md` §3, ``{"ok": false, "error":
  {"code": …}}``) is a failure **whatever the exit code says**;
* a result record carrying a non-empty ``error`` is a failure, likewise;
* a required field the child did not emit is *not verified* — never a pass;
* classification is by the envelope's stable ``code``, never by message text;
* an unrecognised code is a failure, never "done".

Nothing here reads stdout on a success path beyond the declared record fields,
and no caller may pass child stdout into a detail string for a verb whose
success output is secret material (`regista secrets --ref` prints the resolved
secret) — see :mod:`agent_suite.secret_refs`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, assert_never

__all__ = [
    "REFUSAL_CODES",
    "ChildOutcome",
    "ComponentResult",
    "SyntheticCode",
    "evaluate_component_result",
]

#: Cap on any diagnostic we echo from a child, so one runaway child cannot
#: bury the bootstrap report.
_MAX_DETAIL = 800


class ChildOutcome(StrEnum):
    """What the child actually reported.

    ``REFUSED`` is deliberately distinct from ``FAILED``: a refusal means the
    child stopped rather than damage something, which an operator resolves
    differently from a broken step. Both stop the pipeline.
    """

    SUCCESS = "success"
    REFUSED = "refused"
    FAILED = "failed"


class SyntheticCode(StrEnum):
    """Codes this layer assigns when the child supplied none.

    They are namespaced with a ``SUITE_`` prefix so they can never collide with
    a component's own :class:`~regista._errors.ErrorCode`, and so a reader can
    tell "the child said this" from "the suite concluded this".
    """

    #: ``--json`` was requested and stdout was not a single JSON document.
    MALFORMED_RESULT = "SUITE_MALFORMED_RESULT"
    #: The child's result record omitted a field the suite must read to judge
    #: the step. Absence is not a pass.
    INCOMPLETE_RESULT = "SUITE_INCOMPLETE_RESULT"
    #: The child put an ``error`` on its own result record.
    CHILD_REPORTED_ERROR = "SUITE_CHILD_REPORTED_ERROR"
    #: Non-zero exit with no envelope and no record error to explain it.
    UNEXPECTED_EXIT = "SUITE_UNEXPECTED_EXIT"


#: Component error codes that mean "stopped on purpose", not "broke".
#:
#: ``PRINCIPAL_KEY_ALREADY_EXISTS`` is regista's WI-223 refusal to mint a second
#: keypair for a principal that already has a signable one. It is a refusal, and
#: it is recognised **by this code**, not by the words in its message.
REFUSAL_CODES: frozenset[str] = frozenset(
    {
        "PRINCIPAL_KEY_ALREADY_EXISTS",
    }
)


@dataclass(frozen=True)
class ComponentResult:
    """The evaluated outcome of one child invocation.

    ``code`` is the stable machine-readable code to branch on — the child's own
    when it supplied one, otherwise a :class:`SyntheticCode`. ``records`` are
    the child's success payload objects, present only when the outcome is
    ``SUCCESS``, so no caller can read fields off a failed run.
    """

    outcome: ChildOutcome
    code: str | None
    detail: str
    records: tuple[dict[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        match self.outcome:
            case ChildOutcome.SUCCESS:
                return True
            case ChildOutcome.REFUSED | ChildOutcome.FAILED:
                return False
            case other:
                assert_never(other)

    def field(self, name: str) -> Any:
        """Read ``name`` off the single result record.

        Raises :class:`LookupError` when the result is not a single record, so a
        caller cannot silently read ``None`` out of a batch or a failure.
        """
        if len(self.records) != 1:
            raise LookupError(
                f"expected exactly one result record, got {len(self.records)}"
            )
        return self.records[0][name]


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _MAX_DETAIL else flat[: _MAX_DETAIL - 1] + "…"


def _diagnostic(stderr: str, *, fallback: str = "no diagnostic output") -> str:
    """The most useful line of a child's stderr.

    A traceback is reduced to its last line — the exception. The frames are the
    child's business, and an operator reading a bootstrap report needs "vault:
    permission denied", not forty lines of somebody else's call stack. (A
    traceback on a documented error path is itself a bug in the child: CLI
    contract §4 says catch it and emit the envelope. Saying "crashed" rather
    than paraphrasing keeps that visible.)
    """
    text = stderr.strip()
    if not text:
        return fallback
    if "Traceback (most recent call last)" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return f"child crashed with {_clip(lines[-1])}"
    return _clip(text)


def _error_envelope(payload: object) -> dict[str, Any] | None:
    """Return the CLI-contract §3 error object, if this payload is one.

    Accepts both the full envelope (``{"ok": false, "error": {...}}``) and the
    degenerate form some verbs emit (``{"error": {...}}`` with no ``ok``). A
    string-valued ``error`` is *not* an envelope — that is a result record with
    an error on it, handled separately, because it carries no code.
    """
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        return error
    if payload.get("ok") is False:
        # ok:false with no error object still means failure; synthesise one so
        # the caller always has something to branch on.
        return {"code": None, "message": payload.get("detail") or ""}
    return None


def _records(payload: object) -> tuple[tuple[dict[str, Any], ...], str | None]:
    """Normalise a success payload to a tuple of result records."""
    if isinstance(payload, list):
        if not payload:
            return (), "JSON result list is empty"
        if not all(isinstance(item, dict) for item in payload):
            return (), "JSON result list contains a non-object entry"
        return tuple(payload), None
    if isinstance(payload, dict):
        nested = payload.get("results")
        if nested is not None:
            if not isinstance(nested, list) or not nested:
                return (), "JSON results field must be a non-empty list"
            if not all(isinstance(item, dict) for item in nested):
                return (), "JSON results field contains a non-object entry"
            return tuple(nested), None
        return (payload,), None
    return (), (
        "JSON result must be an object or a non-empty list of objects, got "
        f"{type(payload).__name__}"
    )


def evaluate_component_result(
    *,
    command: str,
    returncode: int,
    stdout: str,
    stderr: str,
    require_fields: tuple[str, ...] = (),
) -> ComponentResult:
    """Judge one ``--json`` child invocation.

    ``command`` labels the child in every detail string (``"regista
    provision"``). ``require_fields`` are the record fields the caller will read
    to decide the step; a record missing any of them is ``FAILED``, because a
    field the child did not emit is a fact the suite does not have.

    The exit code is used only as *corroboration*: it can turn an otherwise
    silent run into a failure, but it can never turn a reported error into a
    success. That asymmetry is the whole point — a component that violates CLI
    contract §2 by exiting 0 on an error path must not be able to green a step.
    """
    payload: object | None = None
    parse_error: str | None = None
    if stdout.strip():
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            parse_error = f"stdout is not valid JSON ({exc.msg})"
    else:
        parse_error = "stdout is empty"

    if parse_error is not None:
        return ComponentResult(
            ChildOutcome.FAILED,
            SyntheticCode.MALFORMED_RESULT,
            f"{command} --json exited {returncode} but {parse_error}: "
            f"{_diagnostic(stderr)}",
        )

    envelope = _error_envelope(payload)
    if envelope is not None:
        raw_code = envelope.get("code")
        code = str(raw_code) if raw_code else None
        message = _clip(str(envelope.get("message") or "")) or "no message"
        # Report the contract violation rather than quietly tolerating it: an
        # operator reading "exited 0" next to an error body needs to know the
        # child, not the suite, is the thing to fix (WI-040).
        exit_note = (
            ""
            if returncode != 0
            else " (child exited 0 while reporting an error — "
            "CLI contract §2 violation, treated as failure)"
        )
        detail = f"{command} reported [{code or 'no code'}] {message}{exit_note}"
        if code is not None and code in REFUSAL_CODES:
            return ComponentResult(ChildOutcome.REFUSED, code, detail)
        return ComponentResult(ChildOutcome.FAILED, code, detail)

    records, structure_error = _records(payload)
    if structure_error is not None:
        return ComponentResult(
            ChildOutcome.FAILED,
            SyntheticCode.MALFORMED_RESULT,
            f"{command} --json: {structure_error}",
        )

    # A record-level `error` string is the WI-040 shape: a result object that
    # says the work did not happen, emitted alongside exit 0.
    record_errors = [
        f"{record.get('project') or record.get('principal_id') or 'result'}: "
        f"{_clip(str(record['error']))}"
        for record in records
        if isinstance(record.get("error"), str) and record["error"].strip()
    ]
    if record_errors:
        exit_note = (
            ""
            if returncode != 0
            else " (child exited 0 while reporting an error — "
            "CLI contract §2 violation, treated as failure)"
        )
        return ComponentResult(
            ChildOutcome.FAILED,
            SyntheticCode.CHILD_REPORTED_ERROR,
            f"{command} reported an error on its own result: "
            f"{'; '.join(record_errors)}{exit_note}",
        )

    missing = sorted(
        {field for record in records for field in require_fields if field not in record}
    )
    if missing:
        return ComponentResult(
            ChildOutcome.FAILED,
            SyntheticCode.INCOMPLETE_RESULT,
            f"{command} --json omitted field(s) the suite must read to judge "
            f"this step: {', '.join(missing)} — a field the child did not emit "
            f"is not evidence the work happened",
        )

    if returncode != 0:
        return ComponentResult(
            ChildOutcome.FAILED,
            SyntheticCode.UNEXPECTED_EXIT,
            f"{command} exited {returncode} without reporting an error: "
            f"{_diagnostic(stderr)}",
        )

    return ComponentResult(
        ChildOutcome.SUCCESS,
        None,
        f"{command} succeeded",
        records,
    )
