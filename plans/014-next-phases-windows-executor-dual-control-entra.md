# Plan 014 — Next phases: Windows executor, dual control state store, Entra JWKS, and packaging

**Status:** Proposed — drafted 2026-07-12 after Plan 013 Areas 6–8 landed.  
**Author:** umans-glm-5.2  
**Depends:** Plan 013 (Windows setup protocol, observation adapters, signed receipts,
WinSW, DPAPI, dual control, Entra step-up).  
**Strategic role:** Turn the protocol foundations from Plan 013 into running,
qualified production code. Each phase produces a testable increment.

## What landed in Plan 013 Areas 6–8

| Area | What exists | What's missing |
|------|-------------|----------------|
| 6 — Observation | `windows_observation.py` with stdlib probes; `preflight` CLI | Profile-aware operation sets; real Windows service-account probe |
| 7 — Receipts/WinSW/DPAPI | HMAC-SHA256 signed receipts; WinSW XML generator with runner; DPAPI edge module | Actual `winsw.exe` invocation on Windows; DPAPI user-profile loading; packaging (wheel + installer) |
| 8 — Dual control/Entra | Fail-closed protocol with 14 rejection paths; Entra adapter with fail-closed JWT validation | State store for PENDING→APPROVED→EXECUTED; JWKS key fetching; replay protection |

## Phase 1 — Windows setup executor (turns preflight into install)

**Goal:** `agent-suite setup install` actually installs artifacts, configures
WinSW services, and wires harnesses on a real Windows host.

### WI-1.1 — Profile-aware operation selection

The preflight CLI currently requests ALL operations (`frozenset(SetupOperation)`).
Make it profile-aware: Profile A → WIRE_HARNESSES only; Profile B → + INSTALL_RELEASE;
Profile C → + CONFIGURE_SERVICES. This makes preflight useful for single-operator
profiles that don't need elevation.

**AC:** preflight for Profile A doesn't require elevation or service_account.

### WI-1.2 — Real artifact install executor

Implement the `apply_plan()` function in `windows_setup.py` that takes a
`SetupPlan` (state=READY) and executes it:
- INSTALL_RELEASE: download/verify pinned artifacts, install via pip
- CONFIGURE_SERVICES: call `install_winsw_service()` for each SUITE_SERVICES spec
- WIRE_HARNESSES: call component `install-harness` CLIs
- APPLY_SIGNED_BUNDLE: verify signature, apply config
- REPAIR: re-run idempotent steps
- RESTORE_AND_VERIFY: call `verify_restore`

Each step produces an `ActionReceipt` with APPLIED/FAILED state. The function
returns a `SetupReceipt` with state APPLIED/PARTIAL/FAILED.

**AC:** `agent-suite setup install --dry-run` shows the plan; `--apply` executes
it; re-run is a no-op; a failed step doesn't leave partial state.

### WI-1.3 — Signed receipt signing key custody

Wire the signed receipt to a DPAPI-protected signing key:
- On first run, generate an HMAC key, protect it with DPAPI, store it
- On subsequent runs, unprotect the key, sign receipts
- The `key_id` references the key in a local key registry

**AC:** receipts are signed with a DPAPI-protected key; verification works
after process restart; key rotation produces a new `key_id`.

## Phase 2 — Dual control state store and replay protection

**Goal:** The dual control protocol gains a state store that prevents replay
and tracks PENDING → APPROVED → EXECUTED transitions.

### WI-2.1 — File-based state store

Implement `DualControlStore` (file-based, stdlib):
- `create(request: DualControlRequest) -> None` — stores a pending request
- `approve(request_id: str, approval: DualControlApproval) -> None` — records approval
- `get(request_id: str) -> DualControlRecord | None` — retrieves state
- `mark_executed(request_id: str) -> None` — transitions to EXECUTED
- `list_pending() -> list[DualControlRecord]` — lists pending requests
- `cleanup_expired() -> int` — removes expired requests

The store is a JSON file with a simple lock (fcntl on Linux, msvcrt on Windows).
Each record includes: request, approval (if any), state, created_at, updated_at.

**AC:** a request can only be approved once; an approved request can only be
executed once; expired requests are cleaned up; the store survives process
restarts.

### WI-2.2 — Replay protection in evaluate_approval

Add an optional `store` parameter to `evaluate_approval`:
- If a store is provided, check that the request is in PENDING state
- After approval, transition to APPROVED
- After execution, transition to EXECUTED
- Reject re-evaluation of APPROVED/EXECUTED requests

**AC:** the same approval cannot be used twice; an executed request cannot
be re-approved.

### WI-2.3 — CLI for dual control

Add `agent-suite dual-control` subcommands:
- `request` — create a dual control request (requires a token)
- `approve` — approve a pending request (requires a token)
- `list` — list pending requests
- `execute` — execute an approved request

**AC:** two operators can complete a key rotation via CLI with genuine
separation of duties.

## Phase 3 — Entra JWKS integration and production readiness

**Goal:** The Entra adapter becomes production-ready with automatic JWKS
key fetching and caching.

### WI-3.1 — JWKS key fetching

Use `jwt.PyJWKClient` to fetch and cache Microsoft's JWKS keys from the
discovery endpoint. The `EntraTokenValidator` constructor accepts an
optional `jwks_url` parameter; if provided, keys are fetched automatically.

**AC:** the adapter validates real Entra tokens with signature verification;
keys are cached with TTL; key rotation is handled automatically.

### WI-3.2 — Token refresh and caching

Implement a token cache that stores validated tokens (by `token_hash`) with
their expiry. Re-validation of the same token within its validity window
returns the cached `ValidatedToken` without re-decoding.

**AC:** repeated token validation doesn't re-decode the JWT; expired tokens
are evicted from the cache.

### WI-3.3 — Entra configuration via suite.env

Add Entra configuration to `suite.env`:
```
ENTRA_TENANT_ID=tenant-id-placeholder
ENTRA_CLIENT_ID=client-id-placeholder
ENTRA_AUDIENCE=api://agent-suite
```

The `EntraConfig` is loaded from suite.env via the existing config resolution
layer.

**AC:** Entra validation works with suite.env configuration; no hardcoded
tenant/client IDs.

## Phase 4 — Packaging and distribution

**Goal:** The suite is installable on Windows via a single command.

### WI-4.1 — Wheel packaging with optional extras

Ensure `pyproject.toml` correctly declares all extras:
- `windows` → pywin32 (DPAPI)
- `azure` → PyJWT + azure-identity (Entra)
- `vault` → hvac (Vault secrets)
- `dev` → ruff + mypy + pytest

Add a `[windows-full]` meta-extra that installs all Windows dependencies.

**AC:** `pip install agent-suite[windows]` installs pywin32; `pip install
agent-suite[azure]` installs PyJWT; the core works with no extras.

### WI-4.2 — WinSW binary distribution

Add a script that downloads the WinSW binary from its official GitHub release
and places it in `C:/ProgramData/agent-suite/bin/winsw.exe`. The script
verifies the SHA-256 checksum.

**AC:** `agent-suite setup install-winsw` downloads and verifies the binary;
the WinSW install/remove operations use it.

### WI-4.3 — Windows installer script

A PowerShell script that:
1. Checks prerequisites (Python, pip, PowerShell)
2. Creates `C:/ProgramData/agent-suite/` directory structure
3. Installs agent-suite via pip
4. Runs preflight
5. Configures services (if profile requires)
6. Runs doctor

**AC:** a Windows administrator can install the suite by running one script.

## Sequencing

```
Phase 1 (executor) → Phase 2 (state store) → Phase 3 (Entra JWKS)
                                            → Phase 4 (packaging)
```

Phase 1 is the critical path — it turns the protocol into a running product.
Phase 2 can start in parallel with Phase 1 (different modules). Phase 3
depends on Phase 2 (state store). Phase 4 can start in parallel with Phase 3.

## Non-goals

- A GUI installer (Plan 013 §5 mentions this as a future surface)
- Kubernetes support (deliberately out of scope per blueprint)
- A daemon/control plane (the suite uses OS schedulers, not a supervisor)
- Reimplementing component logic (thin orchestration only)
