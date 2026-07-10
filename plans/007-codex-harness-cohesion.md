# Plan 007 — Codex harness cohesion

**Status:** Proposed 2026-07-10.
**Author:** GPT-5.6 Sol, from a cross-suite Codex integration audit.
**Strategic role:** Add Codex as a first-class local harness without weakening
the suite's install, health, identity, provenance, or capability contracts.

## Ground truth

- The suite contract currently defines `claude | opencode | all`; the CLI
  enforces only those values.
- The documented component interface is positional (`install-harness <target>`)
  and the real component CLIs implement that form. The deployment-simplification
  work corrected bootstrap to use it, but onboard still emits
  `install-harness --harness <target>`. That remaining orchestration defect
  must be corrected before adding another target.
- `run_bootstrap(harness=...)` exists, but the public bootstrap parser does not
  expose `--harness`; operators therefore cannot select a target there today.
- Codex now has documented user/project lifecycle hooks, `AGENTS.md`, shared
  skills, plugins, MCP configuration, and subagents. This makes local Codex
  integration an implementation task, not a speculative interception project.
- The component boundary remains unchanged: agent-suite passes a harness target
  to each component and aggregates its health. It must not implement Codex
  adapters itself.
- `regista` is harness-independent and `dossier` is the human face. Neither
  needs Codex-specific production logic.
- Codex cloud tasks are not equivalent to a local Codex process with the
  operator's user config and suite network access. This plan covers local Codex
  clients; cloud execution requires a separate deployment/security decision.

Authoritative surfaces at planning time:

- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/customization/overview
- https://learn.chatgpt.com/docs/config-file/config-advanced

## Decisions

1. **`codex` is an explicit harness target.** Every suite-owned
   `install-harness` command accepts it even when that component reports an
   honestly unsupported capability.
2. **`all` means all stable suite targets:** `claude`, `opencode`, and
   `codex`. Experimental component-private targets do not silently expand the
   suite contract.
3. **No secrets in Codex config.** Components resolve shared suite configuration
   through `suite.env` and the secret backend. Installers may add hooks,
   skills, MCP wiring, and ownership manifests, but not plaintext DSNs, keys, or
   tokens.
4. **Partial support is named.** A component may report
   `unsupported`/ `degraded` for a Codex feature; it may not return a no-op
   that reads as successfully wired.
5. **One local harness, multiple surfaces.** CLI, IDE, and app sessions using the
   same trusted local config are in scope. Hosted cloud tasks are out of scope
   until their config, identity, network, and secret boundaries are proven.

## Phase 1 — Contract and CLI

### WI-1.1 — Extend the install-harness contract

Update `docs/install-harness-contract.md` with the `codex` target, stable
`all` expansion, user/project config locations, shared skill location, hook
trust step, no-secret rule, uninstall ownership, and JSON result examples.
Freeze the positional component command shape and remove stale option-form
examples.

**AC:**

- The contract distinguishes installed, unsupported, degraded, and failed.
- Every documented component invocation parses against its real CLI; no
  `install-harness --harness` dialect remains.
- Re-run is idempotent and uninstall removes only component-owned entries.
- A clean `all` install expands deterministically to the three stable targets.

### WI-1.2 — Closed harness type and suite CLI validation

Add a closed `HarnessTarget` type (`claude`, `opencode`, `codex`, `all`), expose
`bootstrap --harness`, add Codex to onboard, and pass the target positionally to
component CLIs. Preserve the current effective default (`all`) unless the suite
contract deliberately changes it.

**AC:**

- `agent-suite bootstrap --harness codex --dry-run` and
  `agent-suite onboard --harness codex --dry-run` show Codex commands for
  every harness-aware component.
- Child argv is exactly `(cli, "install-harness", "codex")`; tests fail if the
  selector is dropped or converted back to an unsupported option.
- An invalid harness still fails before any action.
- Unit tests assert exact argv and stable `all` semantics.

## Phase 2 — Health and conformance

### WI-2.1 — Harness-aware component results

Aggregate per-component Codex installation results without smoothing unsupported
features into green. Add a named Codex harness section to doctor output when a
target is configured.

**AC:**

- Missing required Codex provenance is red.
- Optional wake live-turn injection may be `unsupported` without making Tier 0
  unhealthy; the limitation is visible.
- Human and JSON output agree.

### WI-2.2 — Cross-component conformance fixtures

Add synthetic clean, pre-existing, partially wired, and uninstall profiles for
Codex. Assert merge preservation across agent-notes, cairn, acb, and wake.

**AC:**

- Existing user hooks, MCP servers, skills, comments/config values, and unrelated
  plugin entries survive install and uninstall.
- Re-running every installer produces no diff.
- No fixture contains a real hostname, principal, token, or secret.
- Bootstrap, onboard, and CLI tests cover all four harness values, defaulting,
  component order, tier gating, and exhaustive closed-type dispatch.

## Phase 3 — Proof and operator docs

### WI-3.1 — Local Codex interop proof

Extend the suite proof to drive one local Codex session through a read, a shell
tool call, an edit, an agent-notes operation, and an acb capability invocation.
Verify the resulting regista and cairn chains.

**AC:**

- The proof records Codex version, supported hook coverage, component versions,
  and the exact known gaps.
- Missing hook events fail the proof rather than being inferred from final files.
- The proof is repeatable without operator secrets in committed output.

### WI-3.2 — Installation and onboarding docs

Document Codex hook review/trust, sandbox/network expectations, shared skill
discovery, doctor interpretation, uninstall, and local-vs-cloud scope.

**AC:** a new user can install, trust, verify, and remove the Codex wiring using
only suite documentation.

## Explicit no-change decisions

- **regista:** no Codex adapter or plan. It receives the same signed actor,
  session, delegation, and event envelopes as any harness. Add conformance
  fixtures only if a generic envelope gap is discovered.
- **dossier:** no Codex adapter or plan. It renders harness-neutral provenance
  and work state. Add a display-label fixture only if `codex` is currently
  rejected or rendered ambiguously.

## Sequencing

Land the component plans first: agent-notes 019, agent-provenance 011, and acb
007. Wake 006 may land next-session delivery while leaving live-turn wake
unsupported. Then implement this plan and run the cross-component proof.
