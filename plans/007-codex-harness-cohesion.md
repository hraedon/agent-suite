# Plan 007 — Codex harness cohesion

**Status:** In progress 2026-07-17. The target/result contract, public suite
selectors, and false-success corrections are implemented; component Codex
adapters and live conformance remain open.
**Author:** GPT-5.6 Sol, from a cross-suite Codex integration audit.
**Strategic role:** Add Codex as a first-class local harness without weakening
the suite's install, health, identity, provenance, or capability contracts.

## Ground truth

- The suite contract and CLI now accept `claude | opencode | codex | all`.
  `all` deliberately remains the installed stable set (`claude`, `opencode`)
  until every required Codex adapter passes conformance.
- Component invocation is positional (`install-harness <target>`). Bootstrap,
  onboard, and deployment expand `all` centrally and pass only concrete
  targets; the stale option-form invocation has been removed.
- Bootstrap and onboard expose a validated public `--harness` selector.
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
- The installed Codex CLI (`0.144.1` during the 2026-07-17 audit) exposes stable
  `codex plugin` and `codex mcp` commands. Codex plugins can bundle skills,
  hooks, and MCP configuration behind a required `.codex-plugin/plugin.json`.
  Directly copying user files is no longer the only viable distribution model.
- Codex hooks are enabled by default but non-managed command hooks are skipped
  until the operator trusts their exact hash through `/hooks`. Project-local
  hooks also require a trusted project. Managed policy may permit only managed
  hooks, so installation and execution are distinct health states.
- The contract foundation is implemented across agent-suite, agent-notes,
  Cairn, and acb. Explicit Codex requests now return contract-shaped
  `unsupported`, nonzero, and `no_op=false` where adapters do not yet exist.
  Actual Codex plugin/skill/hook/MCP adapters remain to be implemented, and
  wake has not yet joined the contract slice.
- The suite secret resolver and ACB are different boundaries. Codex login state
  remains Codex-owned. External credentials are exposed as ACB capabilities and
  injected only into an invoked child; no component writes them into Codex
  config, plugin files, skills, hooks, or model context.

Authoritative surfaces at the 2026-07-17 refresh:

- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/plugins
- https://learn.chatgpt.com/docs/build-skills
- https://learn.chatgpt.com/docs/extend/mcp
- https://learn.chatgpt.com/docs/config-file/config-advanced

## Decisions

1. **`codex` is an explicit harness target.** Every suite-owned
   `install-harness` command accepts it even when that component reports an
   honestly unsupported capability.
2. **`all` means the currently supported stable suite targets:** initially
   `claude` and `opencode`. `codex` is explicit and fail-closed while its
   adapters are incomplete. It enters `all` atomically only after every required
   component adapter and conformance proof passes. Experimental
   component-private targets do not silently expand the suite contract.
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
6. **Component-owned plugins, suite-owned composition.** Agent-notes, cairn,
   acb, and wake each own their Codex assets and plugin manifest. Agent-suite
   pins and installs the compatible set through its release/marketplace
   metadata; it does not copy their hook or skill implementations into this
   repo. This preserves the thin-orchestrator boundary while giving operators
   one suite-level install path.
7. **No false green.** A parsed-but-unimplemented target is `unsupported`, not
   `no_op`, `installed`, or exit-zero success. Cairn's current Codex skip result
   must be corrected before any umbrella health work.
8. **Codex authentication is out of scope.** Agent-suite does not read, move, or
   provision Codex `auth.json`, keyring entries, ChatGPT sessions, or API keys.
   It verifies that the Codex client reports usable authentication and points
   the operator to Codex's supported login flow.

## Implementation audit — work remaining

| Layer | Current state | Required result | Priority |
|---|---|---|---|
| agent-suite | Contract/selector/result validation landed | aggregate Codex install/doctor after adapters | P0 |
| agent-notes 019 | target accepted; honestly unsupported | skills + orientation/reconciliation hooks + doctor | P0 |
| cairn 011 | false-success fixed; honestly unsupported | lifecycle/tool/subagent hooks + honest coverage and degradation | P0 |
| acb 007 | Codex cred-shim adapter landed (skills/<name>/SKILL.md, create-only, `.system` preserved; e2e/MCP write still honestly unsupported) — acb PR #13 | Codex MCP (e2e) reconciliation; live in-session proof (WI-3.1) | P0 for credentialed lab use |
| wake 006 | plan only | next-session delivery; live wake honestly conditional | P1, not a core blocker |
| suite proof/docs | Claude proof only | correlated local Codex proof and operator runbook | final gate |

The minimum useful Codex slice is agent-notes + cairn + suite install/doctor.
Credentialed administrator work also requires acb. Wake is not on that critical
path and may remain explicitly `next-session-only` or `unsupported` for live
wake.

The suite CLI represents those boundaries as `core`, `credentialed`, and
`full` Codex plugin profiles. The default `core` profile prevents optional wake
from blocking the initial interop proof while still requiring both agent-notes
and Cairn. Codex health keeps successful inspection (`ok`) distinct from the
selected plugin set being usable (`ready`).

The development/release-preparation composition path now builds a validated
local marketplace from sibling component-owned bundles into an explicit output
directory. The read-only `codex-plugins verify` gate separately checks Codex
authentication, marketplace publication, enabled version pins, observable
direct/plugin overlap, and the manual `/hooks` trust handoff. This closes the
local-development portion of WI-0.1; durable publication remains a release
gate, and wake remains honestly unsupported in `full`.

## Phase 0 — Packaging and false-success correction

### WI-0.1 — Freeze the Codex distribution contract

Specify the component-owned plugin manifest, plugin ids, release pinning,
ownership, install/upgrade/remove behavior, local-development path, and how the
suite release exposes the compatible plugin set. Preserve direct component
installers only as a tested development/fallback surface; the operator-facing
suite path uses Codex's supported plugin command.

**AC:** a fixture marketplace containing the four pinned component plugins can
be installed and removed from an isolated `CODEX_HOME`; no component asset is
vendored into agent-suite; unrelated plugins and user config remain unchanged.

### WI-0.2 — Fail closed for unsupported adapters

Correct cairn's Codex no-op result and add a suite-wide conformance assertion
that every accepted target returns one of `installed`, `degraded`,
`unsupported`, or `failed` with matching exit/health semantics.

**AC:** accepting a target without wiring anything cannot be reported as
success, already-installed, or a healthy no-op.

## Phase 1 — Contract and CLI

### WI-1.1 — Extend the install-harness contract

Update `docs/install-harness-contract.md` with the `codex` target, stable
`all` expansion, user/project config locations, shared skill location, hook
trust step, component-plugin ownership, no-secret rule, uninstall ownership,
and JSON result examples.
Freeze the positional component command shape and remove stale option-form
examples.

**AC:**

- The contract distinguishes installed, unsupported, degraded, and failed.
- Every documented component invocation parses against its real CLI; no
  `install-harness --harness` dialect remains.
- Re-run is idempotent and uninstall removes only component-owned entries.
- A clean `all` install expands deterministically to the currently supported
  stable targets. Codex is promoted into that expansion atomically only after
  all required component adapters and conformance tests pass.
- Plugin installation and hook trust are separate states; an installer never
  silently bypasses or persists trust.

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
- Doctor distinguishes the CLI-observable plugin states — absent,
  installed-disabled, installed-enabled — from `codex plugin list --json`. Hook
  trust/activity has no CLI surface in Codex 0.144.5 (it is granted via the
  interactive `/hooks` review), so doctor defers it to the operator rather than
  fabricating trust states; see `docs/install-harness-contract.md` §2.

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
- The ACB capability is synthetic and proves inject-don't-surface: its value is
  absent from the transcript, hook payloads, provenance, process argv, and
  committed proof bundle.

### WI-3.2 — Installation and onboarding docs

Document plugin installation, Codex login as an operator-owned prerequisite,
hook review/trust, managed-policy effects, sandbox/network expectations, shared
skill discovery, doctor interpretation, uninstall, and local-vs-cloud scope.

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

1. Land WI-0.1/WI-0.2 and the closed suite contract so components target one
   packaging/result shape.
2. Implement agent-notes 019, agent-provenance 011, and acb 007 in parallel.
3. Land the suite aggregate install/doctor path and the local correlated proof.
4. Implement wake 006 independently; next-session delivery may land while
   live-turn wake remains unsupported.
