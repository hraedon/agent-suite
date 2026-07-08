# The install-harness contract

**Status:** Contract spec 2026-07-02
**Purpose:** Define the shared `install-harness` interface before any
component implements it, so the four harness-wiring commands (agent-notes,
cairn, acb, agent-wake) converge on one shape rather than four dialects.

This document is the contract each component's `install-harness`
implements. The suite-level `agent-suite bootstrap` calls each
component's `install-harness` in order; it does not define a separate
suite-level wiring command.

---

## 1. Command signature

```
<tool> install-harness <harness> [--dry-run] [--uninstall] [--user <principal_id>]
```

- **`<harness>`**: required, one of `claude | opencode | hermes | all`.
  The `hermes` target is specified in
  [`harness-target-hermes.md`](harness-target-hermes.md).
- **`--dry-run`**: prints the planned changes (what files would be
  created/modified, what env vars set, what hooks registered); acts on
  nothing. Exit 0.
- **`--uninstall`**: reverses a prior `install-harness` — removes the
  files/entries it created, restoring the harness config to its
  pre-install state. Idempotent: uninstalling on a clean profile is a
  no-op, not an error.
- **`--user <principal_id>`**: writes per-user wiring (the user's
  `principal_id`, their default project) into the harness config
  without touching shared/system state. Used by bootstrap step 7
  (per-user onboarding). When omitted, installs system-level wiring
  (the default for a first bootstrap).

## 2. What each harness target requires

### claude

Wires `~/.claude/settings.json` (or the per-user equivalent):
- **Env vars**: the tool's config (`REGISTA_DSN` / `REGISTA_KEY_PATH`
  or the tool's own vars) set in the harness's environment block.
- **Hooks** (cairn only): PreToolUse / PostToolUse / session-start
  hook scripts registered, pointing at the tool's hook entry point.
- **Skills** (agent-notes, acb): skill directories installed under
  `~/.claude/skills/<name>/SKILL.md`.
- **Command shims** (acb): `~/.claude/skills/<name>/SKILL.md` that
  shell to `acb exec cred:<name>`.

### opencode

Wires `~/.config/opencode/opencode.json`:
- **Env vars**: same, in the opencode config's environment block.
- **Plugin** (cairn): the `integrations/opencode/index.js` plugin
  registered.
- **Command shims** (agent-notes, acb):
  `~/.config/opencode/command/<name>.md` stems.
- **Plugin transforms** (agent-notes): the
  `experimental.chat.system.transform` and
  `experimental.session.compacting` hooks registered.

### hermes

Wires `~/.hermes/config.yaml` and `~/.hermes/.env`:
- **Env vars**: the tool's config set in `~/.hermes/.env` (KEY=VALUE, not JSON)
  within a sentinel-managed block (see
  [`harness-target-hermes.md`](harness-target-hermes.md) §3).
- **Plugin** (cairn): a plugin installed at
  `~/.hermes/plugins/observability/cairn/` that registers `pre_tool_call` /
  `post_tool_call` hooks via the `register(ctx)` entry point.
- **Skills** (agent-notes, acb): skill directories installed under
  `~/.hermes/skills/<name>/SKILL.md` (same `SKILL.md` format as Claude Code).
- **Command shims** (acb): `~/.hermes/skills/<name>/SKILL.md` that
  shell to `acb exec cred:<name>`.

See [`harness-target-hermes.md`](harness-target-hermes.md) for the full
path-mapping, env-var wiring, and plugin architecture.

## 3. Idempotency rules

1. **Re-running `install-harness` on an already-wired profile is a
   no-op.** It detects existing wiring and exits 0 with a "already
   installed" message. It does not rewrite files that are already
   correct.
2. **Existing user config is preserved.** If `settings.json` already
   has entries the tool didn't create, those entries stay. The tool
   merges its additions; it does not overwrite the file wholesale.
3. **No secret clobber.** If a harness config already contains a
   secret the tool would set, the existing value is kept and a
   warning is printed (never silently overwritten — the acb
   config-no-clobber lesson).
4. **`--uninstall` removes only what `install-harness` created.** It
   tracks its own additions (by a sentinel comment, a sidecar
   manifest, or a known set of keys) and removes exactly those. User-
   authored config is untouched.

## 4. `--dry-run` output shape

JSON to stdout, human-readable summary to stderr:

```json
{
  "tool": "<tool-name>",
  "harness": "claude",
  "user": "<principal_id|null>",
  "actions": [
    {"kind": "create_file", "path": "~/.claude/skills/file-breadcrumb/SKILL.md", "detail": "install skill"},
    {"kind": "merge_json", "path": "~/.claude/settings.json", "keys": ["env.REGISTA_DSN"], "detail": "set suite env vars"},
    {"kind": "merge_json", "path": "~/.claude/settings.json", "keys": ["hooks.PreToolUse"], "detail": "register cairn hook"}
  ],
  "no_op": false
}
```

- `no_op: true` when the harness is already wired (idempotency rule 1).
- Each action names the file path and what changes. This is what
  `agent-suite bootstrap --dry-run` aggregates across all components.

## 5. Harness validation

Every `install-harness` implementation must support **all three** targets
(`claude`, `opencode`, and `hermes`), even if the work deployment is
Claude-first. The validation contract:

1. `install-harness claude` on a clean profile → `doctor` green.
2. `install-harness opencode` on a clean profile → `doctor` green.
3. `install-harness hermes` on a clean profile → `doctor` green.
4. `install-harness all` on a clean profile → all three wired, `doctor`
   green for all.
5. **Regression guard:** on a profile with an *existing* opencode or
   hermes setup (the operator's local dev), `install-harness opencode` /
   `install-harness hermes` does not break the existing config — verified
   by running `doctor` before and after and confirming no new failures.

This guard is cheap because all harnesses run locally. It extends the
blueprint §4 constraint: "opencode is maintained, not deferred" — and
hermes is held to the same bar.

## 6. Cross-component coordination

Each component implements `install-harness` independently (it owns
its own wiring). The suite repo (`agent-suite`) calls them in
bootstrap order:

```
agent-notes install-harness <harness>
cairn install-harness <harness>
acb install-harness <harness>
agent-wake install-harness <harness>   # Tier 2, optional
```

**Order matters within a single harness:** agent-notes skills and
cairn hooks are independent of each other, but acb's `cred-*` shims
depend on the harness being wired for skill/command execution first.
So: agent-notes → cairn → acb → wake.

If two components write to the same harness config file (e.g., both
write to `settings.json`), they must use a **merge strategy** (JSON
patch, not file overwrite) so the second doesn't clobber the first.
The `--dry-run` output (§4) makes merge conflicts visible before they
happen.

## 7. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (including idempotent no-op) |
| 1 | Failure: harness not found, config file unwritable, etc. |
| 2 | `--dry-run` completed (informational, not an error) |

## 8. Implementing components

| Component | Plan | Scope |
|-----------|------|-------|
| agent-notes | Plan 017 WI-2.1 | Skills + env + opencode plugin transforms |
| cairn (agent-provenance) | Plan 008 WI-1.2 | Hooks (Claude) / plugin (opencode) + default-on env |
| acb | Plan 005 WI-2.1 | Cred shims + capability manifest |
| agent-wake | Plan 004 WI-3.1 | Wake receiver adapter (daemon subscription) |

Each component references this document as its interface contract.
