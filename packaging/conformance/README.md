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

## Use

```toml
# in a component's dev/test dependencies
"agent-suite-conformance==1.0.0"
```

```python
from agent_suite.conformance import (
    KIT_VERSION, CLI_CONTRACT_VERSION,
    SuccessCase, ErrorCase, UsageCase,
    run_success_case, run_error_case, run_usage_case,
    validate_envelope,
)
```

The kit discovers what to test from each component's CLI manifest
(`<tool> contract --json`); see the agent-suite CLI contract for the manifest
shape.

## Provenance

Built from the single source of truth at `src/agent_suite/conformance/` in the
agent-suite repository. `version` here equals `agent_suite.conformance.KIT_VERSION`;
a guard test fails CI if they diverge.

**Namespace caveat.** This wheel ships `agent_suite/conformance/` with no
`agent_suite/__init__.py`, so `agent_suite` resolves as a PEP 420 namespace. That
holds only where nothing else puts a *regular* `agent_suite` package (one with an
`__init__.py`) on `sys.path` — a regular package shadows namespace portions. In
practice consumers (regista, agent-notes) never install agent-suite, so this is
safe; but do not co-install this wheel with an editable/regular `agent-suite` and
expect `agent_suite.conformance` to come from the wheel — it will be shadowed by
the regular package. Develop the kit from the agent-suite source tree instead.
