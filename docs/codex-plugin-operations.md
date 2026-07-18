# Codex plugin operations

Agent-suite composes component-owned Codex plugins; it does not vendor their
skills, hooks, or implementation. The initial supported slices are:

- `core`: agent-notes and Cairn.
- `credentialed`: core plus ACB.
- `full`: credentialed plus agent-wake. Wake is currently unsupported, so a
  full marketplace build or verification fails honestly.

## Build a local marketplace

Use an explicit output directory outside the repositories and user profiles:

```text
agent-suite codex-plugins build-marketplace \
  --profile credentialed \
  --marketplace agent-suite-local \
  --output /path/to/agent-suite-marketplace
```

By default, the command finds component checkouts beside agent-suite. Use
`--workspace-root` for another constellation root. It validates each
component's `.codex-plugin/plugin.json` name and version against the suite pin,
then creates local symlinks and Codex marketplace metadata beneath the explicit
output. It never writes `$CODEX_HOME`, `$HOME/.agents`, or a component checkout.
Only dedicated component distribution bundles are eligible; repository roots
are intentionally not used because Codex may otherwise copy unrelated checkout
state such as virtual environments into its plugin cache.

The output carries `.agent-suite-marketplace.json`. Re-running is idempotent,
but the builder refuses a non-empty directory without that ownership marker and
never replaces a real directory in `plugins/`. `--dry-run` validates every
source without creating the output.

This is a development and release-preparation artifact, not a published release
channel. A release still needs immutable component sources, a durable
marketplace location, publication review, and a tested upgrade policy.

## Install and verify in an isolated profile

For a proof that cannot alter the operator's real Codex profile:

```text
export CODEX_HOME=/path/to/disposable-codex-home
mkdir -p "$CODEX_HOME"
codex plugin marketplace add /path/to/agent-suite-marketplace --json
agent-suite codex-plugins install \
  --profile credentialed --marketplace agent-suite-local
agent-suite codex-plugins verify \
  --profile credentialed --marketplace agent-suite-local
```

`verify` is read-only. It reports these boundaries separately:

1. Codex CLI execution and `codex login status`; authentication remains
   operator-owned and no authentication file or value is read by agent-suite.
2. Marketplace configuration and publication of every pinned version.
3. Installed, enabled plugin state and exact version pins.
4. Direct-installer overlap, where the component doctor exposes enough
   evidence. Agent-notes skills or Cairn hooks active through both paths fail
   readiness; ACB's capability-specific shims are reported separately from its
   generic plugin guidance.
5. Cairn hook trust. Codex exposes trust through interactive `/hooks`, not a
   machine-readable CLI. Verification therefore reports `action_required` and
   `ready: false` until the operator reviews the exact hooks and reruns with
   `--hooks-reviewed`. That flag is an assertion for one invocation and is not
   persisted.

`ok` means no machine check failed, `machine_ready` means the observable
installation is ready, and `ready` additionally requires the explicit hook
trust handoff. The command exits zero only when `ready` is true.

After testing, remove only the selected marketplace plugins:

```text
agent-suite codex-plugins uninstall \
  --profile credentialed --marketplace agent-suite-local
codex plugin marketplace remove agent-suite-local --json
```

The release marketplace name remains `agent-suite`; a local proof should use a
different name so it cannot masquerade as the release source.
