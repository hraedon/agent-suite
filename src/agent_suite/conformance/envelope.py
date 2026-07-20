"""The common CLI error envelope (CLI contract v1 §3).

``build_envelope`` constructs the shape, ``validate_envelope`` checks a
parsed document against it (stdlib-only — the schema at
``data/cli-error-envelope.schema.json`` is the normative statement; this
validator mirrors it for consumers that must stay dependency-free), and
``emit_error`` is the helper a conforming CLI calls on every error path.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def build_envelope(
    code: str,
    message: str,
    *,
    detail: str | None = None,
    retryable: bool = False,
    partial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a contract-v1 error envelope."""
    if not _CODE_RE.match(code):
        raise ValueError(f"error code {code!r} is not SCREAMING_SNAKE")
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
            "retryable": retryable,
            "partial": partial,
        },
    }


def validate_envelope(document: Any) -> list[str]:
    """Return contract violations for a parsed error document (empty = valid)."""
    violations: list[str] = []
    if not isinstance(document, dict):
        return ["envelope is not a JSON object"]
    if document.get("ok") is not False:
        violations.append("envelope 'ok' is not false")
    error = document.get("error")
    if not isinstance(error, dict):
        return violations + ["envelope 'error' is not an object"]
    code = error.get("code")
    if not isinstance(code, str) or not _CODE_RE.match(code):
        violations.append(f"error 'code' {code!r} is not a SCREAMING_SNAKE string")
    if not isinstance(error.get("message"), str):
        violations.append("error 'message' is not a string")
    if "detail" in error and not isinstance(error["detail"], (str, type(None))):
        violations.append("error 'detail' is not a string or null")
    if not isinstance(error.get("retryable"), bool):
        violations.append("error 'retryable' is not a boolean")
    partial = error.get("partial")
    if partial is not None:
        if not isinstance(partial, dict):
            violations.append("error 'partial' is not an object or null")
        else:
            succeeded = partial.get("succeeded")
            failed = partial.get("failed")
            if not isinstance(succeeded, int) or succeeded < 0:
                violations.append("partial 'succeeded' is not a non-negative integer")
            if not isinstance(failed, int) or failed < 1:
                violations.append("partial 'failed' is not a positive integer")
    unknown = set(error) - {"code", "message", "detail", "retryable", "partial"}
    if unknown:
        violations.append(f"error object has unknown fields: {sorted(unknown)}")
    unknown_top = set(document) - {"ok", "error"}
    if unknown_top:
        violations.append(f"envelope has unknown fields: {sorted(unknown_top)}")
    return violations


def emit_error(
    code: str,
    message: str,
    *,
    detail: str | None = None,
    retryable: bool = False,
    partial: dict[str, Any] | None = None,
    json_mode: bool = False,
) -> int:
    """Report an error per the contract and return the exit code (1).

    Under ``--json`` the envelope is the single stdout document; otherwise
    the message (and detail) go to stderr. Either way the caller returns
    the value returned here — no path prints an error and exits 0.
    """
    if json_mode:
        print(
            json.dumps(
                build_envelope(
                    code,
                    message,
                    detail=detail,
                    retryable=retryable,
                    partial=partial,
                ),
                indent=2,
            )
        )
    else:
        print(f"error: {message}", file=sys.stderr)
        if detail:
            print(f"  {detail}", file=sys.stderr)
    return 1
