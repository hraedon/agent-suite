# The install-harness contract

**Status:** Contract spec 2026-07-02; Codex target added 2026-07-17
**Purpose:** Define the shared `install-harness` interface so agent-notes,
Cairn, acb, and agent-wake converge on one shape rather than four dialects.

Each component owns its harness integration. Agent-suite invokes those
component commands in order; it does not implement their adapters.

## 1. Command signature

```text
<tool> install-harness <harness> [--dry-run] [--uninstall] [--user <principal_id>]
```

- `<harness>` is required and is one of `claude | opencode | codex | all`.
- `all` expands, in order, to the currently supported public targets: `claude`
  and `opencode`. `codex` remains explicitly selectable and fails honestly
  until every required component adapter passes conformance. A
  component-private target such as Cairn's `hermes` remains explicitly
  selectable from that component, but is never included in the suite `all`.
- `--dry-run` reports planned changes without mutating files.
- `--uninstall` reverses only the calling component's owned changes.
- `--user <principal_id>` writes per-user wiring without touching shared state.

The harness selector is positional. `install-harness --harness codex` is not a
supported dialect.

## 2. Target requirements

### Claude

Wires `~/.claude/settings.json` or its per-user equivalent:

- Component configuration in the harness environment block.
- Cairn lifecycle and tool-call hooks.
- Agent-notes and acb skills under `~/.claude/skills/`.
- acb command shims that invoke capabilities without embedding credentials.

### OpenCode

Wires `~/.config/opencode/opencode.json`:

- Component configuration in the environment block.
- Cairn's owned plugin registration.
- Agent-notes and acb command stems.
- Agent-notes system-transform and compaction hooks.

### Codex

Codex assets are packaged as component-owned plugins. Each component owns its
plugin manifest, skills, hooks, MCP declarations, fallback installer, and
uninstall manifest. Agent-suite pins and composes the compatible plugin set but
does not copy component assets into this repository.

- User configuration and installed-plugin state live under `$CODEX_HOME`
  (normally `~/.codex`). User-scoped shared skills live separately under
  `$HOME/.agents/skills`; repo-scoped skills live under `.agents/skills`.
- Project-local configuration is changed only by a component that owns the
  relevant entry and only after the project is trusted.
- Agent-notes and acb may expose skills. Components may declare owned MCP wiring
  through their plugins.
- Cairn owns provenance hook declarations. Installing a plugin means those
  declarations are present; it does not mean command hooks are trusted or have
  executed.
- Non-managed command hooks remain inactive until the operator reviews and
  trusts their exact hash through Codex's `/hooks` flow. Project-local hooks
  additionally require a trusted project. Managed policy may prohibit
  non-managed hooks.
- Codex login state is operator-owned. Installers do not read, copy, write, or
  provision Codex authentication material.

Plugin installation, hook trust, and observed activity are separate health
states. Doctor must distinguish plugin absent, installed-disabled, hooks
awaiting trust, hooks blocked by managed policy, wired-but-silent, and active.
An installer never bypasses or persists trust for the operator.

## 3. Safety and idempotency

1. Re-running an already-correct install is an installed no-op and exits 0.
2. Existing user config, hooks, MCP servers, skills, comments, and unrelated
   plugins are preserved.
3. Existing secret-bearing config is never silently overwritten.
4. Uninstall removes only entries recorded in the calling component's ownership
   manifest.
5. Codex config, plugin files, skills, hooks, and MCP declarations contain no
   plaintext DSN password, signing key, token, password, or resolved capability
   secret.

## 4. Result shape and semantics

JSON results use this shape; a human form may accompany it:

```json
{
  "tool": "<tool-name>",
  "harness": "codex",
  "user": "<principal_id|null>",
  "status": "installed",
  "actions": [
    {
      "kind": "install_plugin",
      "path": "<component-owned-plugin>",
      "detail": "register component plugin"
    }
  ],
  "no_op": false
}
```

`status` is one of `installed | degraded | unsupported | failed`.

- `installed` means the component's required assets are present. It does not
  imply that Codex hooks have been trusted or observed.
- `degraded` names a real, bounded limitation. It is successful only where an
  explicit suite-tier policy permits that limitation; absent such a policy,
  both the component and suite fail closed.
- `unsupported` means the target parsed but the component did not wire it.
- `failed` means an attempted operation did not complete safely.
- `no_op: true` is valid only for an already-installed or already-absent
  idempotent state. A parsed but unwired adapter is never a no-op success.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Installed success, including an idempotent installed no-op; degraded only with an explicit permitting policy |
| 1 | Failed, unsupported, or degraded without a permitting policy |
| 2 | Supported dry-run completed without action |

An unsupported dry-run exits 1: unsupported takes precedence over the
informational dry-run state.

## 5. Validation

Every suite-facing implementation accepts every declared target, even when a
component initially returns honest `unsupported` for one:

1. Claude clean install and reinstall preserve unrelated config.
2. OpenCode clean install and reinstall preserve unrelated config.
3. Codex reports installed/degraded only when component-owned wiring exists;
   otherwise it reports unsupported and exits non-zero.
4. `all` expands deterministically to Claude and OpenCode and never installs
   candidate or component-private targets implicitly. Codex is added to `all`
   atomically only after all required adapters and conformance tests pass.
5. Uninstall restores a pre-existing profile byte-for-byte except for owned
   entries whose removal necessarily changes serialization.

## 6. Cross-component composition

For every harness-aware component, agent-suite expands `all` itself and invokes
each concrete target positionally. Component install order remains:

```text
agent-notes install-harness <harness>
cairn install-harness <harness>
acb install-harness <harness>
agent-wake install-harness <harness>
```

Where a component exposes `--json`, the suite appends it and requires a
contract-shaped result. Empty, malformed, non-object, or status-less JSON fails
closed. One concrete invocation must return exactly one record, whose string
`tool` and `harness` fields exactly match the CLI and concrete target the suite
invoked; duplicates and valid-looking results for another component or target
also fail closed. Only a genuinely legacy component without a JSON install surface may
use exit-zero as its sole success signal; non-zero is always failure regardless
of prose such as “already installed” or “no-op.”

Agent-notes establishes the agent-facing skills, Cairn establishes provenance,
acb adds capability shims, and wake adds signaling. Components that touch the
same config use surgical merge and ownership manifests rather than replacing
the file.

For Codex, direct component installers remain development and fallback
surfaces. The operator-facing suite release installs its release-pinned,
compatible component-plugin set through Codex's supported plugin mechanism.

## 7. Implementing components

| Component | Plan | Scope |
|-----------|------|-------|
| agent-notes | Plan 019 | Skills, orientation/reconciliation hooks, doctor |
| Cairn | Plan 011 | Lifecycle/tool/subagent hooks, scope attestation, doctor |
| acb | Plan 007 | Skills/MCP reconciliation and inject-only execution |
| agent-wake | Plan 006 | Next-session delivery; live wake may remain unsupported |
