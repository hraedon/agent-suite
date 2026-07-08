# Hermes harness target — design spec

**Status:** Proposed 2026-07-08
**Purpose:** Define how each suite component wires into Hermes Agent as a third
harness target alongside `claude` and `opencode`.

This document extends [`install-harness-contract.md`](install-harness-contract.md)
to add `hermes` as a supported `<harness>` value. Each component's
`install-harness hermes` follows the same contract: idempotent, `--dry-run`,
`--uninstall`, no-secret-clobber, sidecar manifest for tracking.

---

## 1. Why Hermes is a distinct target

Hermes Agent (by Nous Research) is an AI agent framework that runs in
terminals, messaging platforms, and IDEs. Like Claude Code and opencode, it
executes tool calls against a real system. Unlike either:

- **No JSON settings file.** Hermes uses `~/.hermes/config.yaml` (YAML, not
  JSON) for behavioral config and `~/.hermes/.env` for secrets/credentials.
- **Plugin system, not hook scripts.** Hermes plugins are Python packages at
  `~/.hermes/plugins/<category>/<name>/` with a `plugin.yaml` manifest and a
  `register(ctx)` entry point. They register hooks via
  `ctx.register_hook(hook_name, callback)`.
- **Built-in `pre_tool_call` / `post_tool_call` hooks.** Hermes already fires
  these observer hooks on every tool dispatch with `tool_name`, `args`,
  `result`, `session_id`, `tool_call_id`, `turn_id`, `duration_ms`, `status`.
  This is the exact interception point cairn needs — no core change required.
- **Skills at `~/.hermes/skills/`.** Same `SKILL.md` format as Claude Code.

## 2. Path mapping

| Artifact | Claude | opencode | Hermes |
|----------|--------|----------|--------|
| Skills | `~/.claude/skills/<name>/SKILL.md` | `~/.config/opencode/command/<name>.md` | `~/.hermes/skills/<name>/SKILL.md` |
| Env vars | `settings.json["env"]` | `opencode.json["env"]` or tool config | `~/.hermes/.env` (KEY=VALUE) |
| Hooks (cairn) | `settings.json["hooks"]` entries | plugin in `opencode.json["plugin"]` | plugin at `~/.hermes/plugins/observability/cairn/` |
| Shims (acb) | `~/.claude/skills/<name>/SKILL.md` | `~/.config/opencode/command/<name>.md` | `~/.hermes/skills/<name>/SKILL.md` |
| MCP servers | `settings.json["mcpServers"]` | `opencode.json["mcp"]` | `~/.hermes/config.yaml` under `mcp_servers` |
| Sidecar manifest | `~/.claude/.<tool>-harness.json` | `~/.config/opencode/.<tool>-harness.json` | `~/.hermes/.<tool>-harness.json` |

## 3. Env var wiring

Hermes `.env` is KEY=VALUE format (not JSON). Suite env vars are secret refs
(`vault:...`, `akv:...`) and connection strings — they belong in `.env`, not
`config.yaml` (which is for behavioral settings only, per Hermes convention).

`install-harness hermes` appends managed entries to `~/.hermes/.env` with a
sentinel comment for idempotent tracking:

```env
# BEGIN <tool>-harness-managed
REGISTA_DSN=postgresql://regista_service@suite-db.example:5432/regista
REGISTA_KEY_PATH=vault:secret/agent-suite/regista#signing_key
# END <tool>-harness-managed
```

`--uninstall` removes only the lines between the sentinels. Pre-existing entries
outside the sentinel block are never touched (contract §3 rule 2).

If a key already exists outside the managed block with a different value, the
installer warns and skips (no clobber, contract §3 rule 3).

## 4. cairn attestation via Hermes plugin

The cairn Hermes plugin lives at `~/.hermes/plugins/observability/cairn/` and
consists of:

- `plugin.yaml` — manifest declaring `pre_tool_call`, `post_tool_call`,
  `on_session_start`, `on_session_end` hooks.
- `__init__.py` — `register(ctx)` function that registers hook callbacks.

The hook callbacks call the existing `CairnAdapter` API in-process (not via
stdin bridge):

- `pre_tool_call` → `adapter.begin_tool_call(tool, tool_args, files=...)`
  → stores `work_item_id` in a session-scoped dict keyed by `tool_call_id`.
- `post_tool_call` → `adapter.end_tool_call(work_item_id, result_summary=...)`
  → clears the entry.
- `on_session_start` → `adapter.attest_session(...)`.
- `on_session_end` → cleanup session state.

Config resolution reuses cairn's existing `_config.py` (env-var precedence:
process env → legacy alias → suite.env file). No new config path.

The adapter is lazily initialized on first `pre_tool_call` (not at plugin
load time) so a missing regista DSN doesn't crash Hermes startup — it degrades
silently with a logged warning, matching the Claude hook's `CAIRN_DISABLE`
behavior.

## 5. acb Hermes adapter

`HermesAdapter` in `adapters.py`:

- `config_path` = `~/.hermes/config.yaml`
- `shims_path` = `~/.hermes/skills`
- `available()` = `config_path.is_file()`
- `mcp_servers()` = parse `mcp_servers` section from YAML
- `command_shims()` = `{d.name for d in skills.iterdir() if (d / "SKILL.md").is_file()}`
- `add_mcp_server()` = merge into `mcp_servers` section, backup-first
- `write_skill_shim()` = create `skills/<name>/SKILL.md`

YAML parsing uses `pyyaml` (available in any Hermes installation; the adapter
is only loaded when Hermes is present).

## 6. agent-wake Hermes integration

agent-wake is still in design phase (no `install-harness` yet). When it lands,
the Hermes target will install a plugin at `~/.hermes/plugins/signaling/wake/`
that:
- Subscribes to wake events (HTTP webhook or regista NOTIFY).
- Delivers via Hermes's in-session context injection (equivalent to opencode's
  `session.prompt({noReply: true})`).

For now, the Hermes target is documented as planned.

## 7. Dual-harness validation (contract §5 amendment)

The validation contract extends to three targets:

1. `install-harness claude` → doctor green.
2. `install-harness opencode` → doctor green.
3. `install-harness hermes` → doctor green.
4. `install-harness all` → all three wired, doctor green for all.

## 8. Bootstrap ordering

No change to the bootstrap order (§1 of bootstrap-contract.md). The harness
target is passed to each component's `install-harness` call:

```
agent-notes install-harness hermes
cairn install-harness hermes
acb install-harness hermes
```

`agent-suite bootstrap --harness hermes` (new flag) runs the install order
with `hermes` as the target for each component's `install-harness` call.
Default remains `all` (all three harnesses).
