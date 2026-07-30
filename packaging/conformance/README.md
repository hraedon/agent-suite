# agent-suite-conformance

The CLI contract v1 conformance kit for the agent suite (Plan 018 WI-2). One
centrally versioned, stdlib-only package that every suite
component depends on as a normal pinned version — so there is exactly one kit,
never per-repo copies to drift.

## What it provides

`agent_suite.conformance` — success/error/usage/broken-pipe case runners and the
common error-envelope validator that hold each suite CLI to the contract in
`docs/cli-contract.md`:

- stdout under `--json` is exactly one JSON document (or documented NDJSON),
  zero non-JSON bytes;
- documented error paths exit nonzero with the common error envelope;
- usage errors exit 2; broken pipe exits without a traceback;
- error output carries no secret material.

It also ships `assert_cases_declared` / `ConformanceGateError`, the meta-guard
that keeps a gate from silently enforcing nothing (see below).

## Use

```toml
# in a component's dev/test dependencies
"agent-suite-conformance==1.1.0"
```

```python
from agent_suite.conformance import (
    KIT_VERSION, CLI_CONTRACT_VERSION,
    SuccessCase, ErrorCase, UsageCase, BrokenPipeCase, Framing,
    run_success_case, run_error_case, run_usage_case, run_broken_pipe_case,
    validate_envelope,
    assert_cases_declared, ConformanceGateError,
)
```

The kit discovers what to test from each component's CLI manifest
(`<tool> contract --json`); see the agent-suite CLI contract for the manifest
shape.

### Meta-guard (new in 1.1.0, WI-026)

A conformance gate's failure mode must not be "silently passes." Call
`assert_cases_declared` once at module top, right after the kit import, so an
empty case dimension fails loudly at collection time instead of looking like a
green run:

```python
assert_cases_declared(
    minimum=1,
    success=SUCCESS_CASES,
    error=ERROR_CASES,
    usage=USAGE_CASES,
    broken_pipe=BROKEN_PIPE_CASES,
)
```

It raises `ConformanceGateError` (an `AssertionError` subclass) if any named
group has fewer than `minimum` cases, and refuses a no-group call. This is one
half of the defense-in-depth cure for the 2026-07-24 silent-skip bug; the other
half is a meta test that runs the gate as a subprocess and asserts ≥1 case
*passed* (not all-skipped). See the agent-suite CLI contract §7 for the full
rationale and the meta-test shape.

## Provenance

Built from the single source of truth at `src/agent_suite/conformance/` in the
agent-suite repository. `version` here equals `agent_suite.conformance.KIT_VERSION`;
a guard test fails CI if they diverge.

**How the build finds the source.** A custom Hatch build hook (`hatch_build.py`,
registered under `[tool.hatch.build.hooks.custom]`) force-includes the source of
truth — no symlink, no copy. It resolves the source per build context:

- **From the monorepo source tree** it force-includes the canonical
  `../../src/agent_suite/conformance` subtree into `agent_suite/conformance`.
- **Building a wheel from an extracted sdist** it uses the subtree the sdist
  already materialized at `agent_suite/conformance` (the sdist also ships
  `hatch_build.py` itself, so that step is self-contained).

If neither the canonical nor the sdist-local subtree exists, the hook fails with
a clear error. A symlink is deliberately NOT used: Git for Windows with
`core.symlinks=false` checks a link out as a stray text file holding the target
path, which would silently ship nothing. The kit is never copied (Plan 018 WI-2)
— the hook reads the one maintained subtree, so the published kit cannot drift
from it. The hook only ever force-includes the conformance subtree, so neither
artifact sweeps in the rest of `agent_suite`.

**Namespace caveat.** This wheel ships `agent_suite/conformance/` with no
`agent_suite/__init__.py`, so `agent_suite` resolves as a PEP 420 namespace. That
holds only where nothing else puts a *regular* `agent_suite` package (one with an
`__init__.py`) on `sys.path` — a regular package shadows namespace portions. In
practice consumers (regista, agent-notes) never install agent-suite, so this is
safe; but do not co-install this wheel with an editable/regular `agent-suite` and
expect `agent_suite.conformance` to come from the wheel — it will be shadowed by
the regular package. Develop the kit from the agent-suite source tree instead.
