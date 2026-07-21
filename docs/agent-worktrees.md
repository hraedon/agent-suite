# Isolated dev environments for concurrent agents (Plan 019 B0)

**Status:** Adopted 2026-07-20 (Plan 019 B0).

## The rule

**Concurrent agents do not share a working tree.** When more than one agent (or
an agent and a human) may touch the same repo at the same time, each gets its own
`git worktree`. This is the default, not an ad-hoc rescue.

## Why

A working tree holds exactly one branch and one set of uncommitted edits. Two
agents in one clone means:

- one agent's uncommitted work is invisible to the other (no isolation), and
- a `git add -A`, `git checkout`, `git stash`, or `git reset` by the second agent
  silently clobbers the first's work.

This is not hypothetical: in the 2026-07-20 regista 0.5.3 release session two
agents collided in a single tree, and the only thing that prevented lost work was
reaching for `git worktree` by hand. B0 makes that reach the default so the
failure mode cannot recur by omission. A `git worktree` shares the repo's object
store and history but gives each checkout its own branch, index, and files — the
isolation we want without a second clone's disk or fetch cost.

## The habit — `scripts/agent-worktree`

```
scripts/agent-worktree <repo> [<name>] [--base <ref>] [--branch <name>]
```

- `<repo>` — a suite member directory name resolved under `/projects`
  (`regista`, `agent-notes`, …) or an absolute path to a git repo.
- `<name>` — a short slug for the agent/task. Defaults to `$AGENT_NAME`, else
  `$USER`. Names the worktree directory and, unless `--branch` is given, the
  branch (`agent/<name>`).
- `--base` — ref to branch from. Default: the repo's `origin/main`, else `main`.
  For deliberate cross-member work, base on a sibling's branch explicitly (see
  Plan 019 B2's `DEV_AGAINST` escape hatch — same intent, one obvious switch).
- `--branch` — an explicit branch name, overriding `agent/<name>`.

It is **idempotent**: a second call for the same repo+name prints the existing
worktree's path and exits 0. Diagnostics go to **stderr**; the **last line of
stdout is the worktree path**, so it composes:

```bash
cd "$(scripts/agent-worktree regista wi-212-stream-discipline | tail -1)"
```

The helper also wires the new worktree's `core.hooksPath` to `githooks/` (so the
identifier gate travels with the checkout) when the target repo ships
`scripts/install-git-hooks.sh`.

### Layout

```
/projects/.worktrees/<name>/<repo>
```

matching the convention already in use (`/projects/.worktrees/codex-support/…`).
Override the root with `WORKTREE_ROOT` and the projects root with
`PROJECTS_ROOT` if needed.

## Lifecycle

- **Create:** `scripts/agent-worktree <repo> <your-task-slug>`, then `cd` into
  the printed path and work there.
- **List:** `git -C /projects/<repo> worktree list`.
- **Finish:** merge/push your branch as usual, then from the main clone
  `git worktree remove /projects/.worktrees/<name>/<repo>` and delete the branch
  if it's done. `git worktree prune` cleans up removed-by-hand trees.

## Enforcement (per `docs/process-calibration.md` §4)

Honestly **layer 3/4**: nothing forces a foreign harness to use a worktree, so
this is a convention plus a helper, not a store- or CI-enforced control. What it
buys is the removal of the *shared tree* — the object the standing rule **never
`git add -A` in a shared tree** exists to protect. With per-agent worktrees there
is less shared tree for that rule to defend. Treat the helper as the paved path,
not a boundary; the boundary against lost work remains agent judgment plus the
`add -A` discipline.

## Non-goals

- **No agent-assignment orchestrator.** The operator decides which agent works in
  which worktree; this is a helper and a habit, not a scheduler.
- **No forced isolation.** A single agent working alone in the main clone is fine;
  the rule binds *concurrent* access.
