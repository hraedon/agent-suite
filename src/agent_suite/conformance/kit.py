"""Behavioral conformance checks for CLI contract v1 (Plan 018 WI-2).

Each check runs a real subprocess against the component's CLI and returns
a list of contract violations (empty = conformant). Components declare
cases (fixtures) and parameterize pytest over them; the checks themselves
live only here, centrally versioned.

The checks prove the contract, not the implementation: stream discipline
(§1), exit-code taxonomy (§2), the error envelope (§3), traceback and
broken-pipe robustness (§4), and secret redaction (§3). Output honesty
(§5) and manifest discovery (§6) are P1 — cases for them extend these
dataclasses rather than forking the kit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from agent_suite.conformance.envelope import validate_envelope

_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Value planted in per-case env vars to prove error paths never echo
# secret material (contract §3 redaction). Cases list the env var *names*
# whose values must never surface; the kit plants this sentinel there.
SENTINEL_SECRET = "conformance-sentinel-3f9d2c"


class Framing(Enum):
    DOCUMENT = "document"
    NDJSON = "ndjson"


@dataclass(frozen=True)
class SuccessCase:
    """A verb invocation that must succeed with pure JSON stdout."""

    name: str
    argv: tuple[str, ...]
    framing: Framing = Framing.DOCUMENT
    env: Mapping[str, str] = field(default_factory=dict)
    unset_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class ErrorCase:
    """A documented failure that must exit nonzero with the envelope."""

    name: str
    argv: tuple[str, ...]
    expect_code: str | None = None
    json_mode: bool = True
    env: Mapping[str, str] = field(default_factory=dict)
    unset_env: tuple[str, ...] = ()
    secret_env_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class UsageCase:
    """A malformed invocation that must exit 2 (argparse usage error)."""

    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class BrokenPipeCase:
    """A verb whose stdout is closed early; it must not traceback."""

    name: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)


CASE_TIMEOUT: float = 60.0


def _run(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    unset_env: tuple[str, ...] = (),
    timeout: float = CASE_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, "PYTHONIOENCODING": "utf-8", **env}
    for name in unset_env:
        merged.pop(name, None)
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            env=merged,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=124,
            stdout="",
            stderr=f"conformance: timed out after {timeout}s",
        )


def run_success_case(case: SuccessCase) -> list[str]:
    """Contract §1 + §2: exit 0, stdout is pure JSON, no traceback."""
    proc = _run(case.argv, case.env, case.unset_env)
    violations: list[str] = []
    if proc.returncode != 0:
        violations.append(
            f"exit {proc.returncode}, expected 0; stderr: {proc.stderr[-500:]!r}"
        )
    if _TRACEBACK_MARKER in proc.stderr:
        violations.append("traceback on a documented success path")
    stdout = proc.stdout.strip()
    if not stdout:
        violations.append("empty stdout on a JSON success path")
        return violations
    match case.framing:
        case Framing.DOCUMENT:
            try:
                json.loads(stdout)
            except json.JSONDecodeError as exc:
                violations.append(
                    f"stdout is not a single JSON document ({exc}); "
                    f"first 200 bytes: {stdout[:200]!r}"
                )
        case Framing.NDJSON:
            for lineno, line in enumerate(stdout.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    violations.append(
                        f"NDJSON line {lineno} is not JSON: {line[:200]!r}"
                    )
    return violations


def run_error_case(case: ErrorCase) -> list[str]:
    """Contract §2 + §3: nonzero exit, envelope on stdout, no leaks."""
    env = dict(case.env)
    for name in case.secret_env_names:
        env[name] = SENTINEL_SECRET
    proc = _run(case.argv, env, case.unset_env)
    violations: list[str] = []
    if proc.returncode == 0:
        violations.append(
            "exit 0 on a documented error path (the fail-open class); "
            f"stdout: {proc.stdout[:200]!r} stderr: {proc.stderr[:200]!r}"
        )
    if proc.returncode == 2:
        violations.append("exit 2 (usage) on an operational error path")
    if _TRACEBACK_MARKER in proc.stderr or _TRACEBACK_MARKER in proc.stdout:
        violations.append("traceback on a documented error path")
    if case.secret_env_names and SENTINEL_SECRET in proc.stdout + proc.stderr:
        violations.append("secret material leaked into error output")
    if case.json_mode:
        stdout = proc.stdout.strip()
        if not stdout:
            violations.append("no envelope on stdout for a --json error path")
            return violations
        try:
            document = json.loads(stdout)
        except json.JSONDecodeError:
            violations.append(
                f"--json error stdout is not JSON: {stdout[:200]!r}"
            )
            return violations
        violations.extend(validate_envelope(document))
        if case.expect_code is not None and not violations:
            actual = document["error"]["code"]
            if actual != case.expect_code:
                violations.append(
                    f"error code {actual!r}, expected {case.expect_code!r}"
                )
    return violations


def run_usage_case(case: UsageCase) -> list[str]:
    """Contract §2: malformed invocations exit 2, without traceback."""
    proc = _run(case.argv, {})
    violations: list[str] = []
    if proc.returncode != 2:
        violations.append(f"exit {proc.returncode}, expected 2 (usage error)")
    if _TRACEBACK_MARKER in proc.stderr:
        violations.append("traceback on a usage error")
    return violations


def run_broken_pipe_case(case: BrokenPipeCase) -> list[str]:
    """Contract §4: closing stdout early must not produce a traceback."""
    if sys.platform == "win32":
        return []  # SIGPIPE semantics don't apply; nothing to prove here.
    with subprocess.Popen(
        list(case.argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, **case.env},
    ) as proc:
        assert proc.stdout is not None
        proc.stdout.read(1)
        proc.stdout.close()
        stderr = proc.stderr.read() if proc.stderr else b""
        proc.wait(timeout=120)
    if _TRACEBACK_MARKER.encode() in stderr:
        return ["traceback on broken stdout pipe"]
    return []
