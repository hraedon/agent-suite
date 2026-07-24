# agent-suite-conformance

CLI contract v1 conformance kit for the agent suite (Plan 018 WI-2, Plan 019 B1).

One centrally versioned package, owned by agent-suite, consumed pinned by every
component — never copied, so there is exactly one kit to drift from.

## Usage

Components add `agent-suite-conformance==1.0.0` to their dev extra and declare
conformance cases (fixtures) parameterized over the kit's check functions:

```python
from agent_suite_conformance import (
    SuccessCase,
    ErrorCase,
    UsageCase,
    BrokenPipeCase,
    run_success_case,
    run_error_case,
    run_usage_case,
    run_broken_pipe_case,
)
```

## Versioning

`KIT_VERSION` identifies the kit in recorded conformance results
(`data/cli-conformance.json`); `CLI_CONTRACT_VERSION` is the contract revision
the kit enforces (`docs/cli-contract.md` in agent-suite).
