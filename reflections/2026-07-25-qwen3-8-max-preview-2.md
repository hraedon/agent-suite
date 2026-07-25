---
model: qwen3.8-max-preview
datetime: 2026-07-25T22:00 UTC
project: agent-suite
---

# Session Reflection — 2026-07-25 (Plan 015 Gate 1 closure)

**Work summary:** Verified Plan 015 Gate 1 exit criteria against the probe-emitted
feature matrix and dossier's 649-test suite. Fixed a stale k8s image tag
(0.0.1 → 0.1.0 in deploy/k8s/deployment.yaml) that was the sole test failure.
Updated the plan status line to record Gate 1 complete with per-WI evidence.

---

## On the project

The probe-emitted feature matrix continues to be the family's strongest
structural asset. Closing Gate 1 was a verification exercise, not a discovery
exercise — the matrix said "all Profile B rows pass" and the test suite
confirmed it. That's exactly how a release gate should work: the answer is
already machine-determined before a human or agent sits down to close it.

What's less mature: the plan file itself is still hand-maintained prose. The
status line I just updated is the third or fourth rewrite of that paragraph.
A machine-readable gate-status field (even a YAML frontmatter block) would let
tooling answer "is Gate 1 done?" without parsing English. Low priority, but
the plan is accumulating enough history that the prose is getting unwieldy.

## On the work done

Confident in the closure. The evidence is straightforward:
- Feature matrix: all Profile B rows probe-emitted pass (only non-pass is
  GJ-9 upgrade/rollback, Profile A, Gate 4 scope, tracked by WI-025).
- Dossier: 649 passed, 17 skipped, 1 xfailed. The xfail is the knowledge
  create note route (regista reserved-transition block) — a known issue that
  doesn't affect the Gate 1 AC because the AC is about the review journey,
  not note creation.
- Architecture boundary tests actively reject private imports and direct SQL.
- Ruff + mypy --strict clean.

The k8s image tag fix was trivial but worth noting: it failed because the
SUITE.lock version was bumped to 0.1.0 in commit f07e5fe but the deployment
manifest wasn't updated in the same commit. The test caught it correctly.

## On what remains

1. **Commit and push** the dossier deployment fix and the agent-suite plan
   update. These are local-only right now.
2. **Gate 2** is next: immutable lock, test-from-lock CI, release bundle,
   supply-chain gates. The critical path item is replacing the current
   SUITE.lock format with one that pins by immutable revision + digest.
3. **The knowledge create xfail** (regista TRANSITION_VIA_APPEND_BLOCKED)
   should get its own work item if it doesn't already have one. It's not a
   Gate 1 blocker but it will surface as a user-visible bug in the knowledge
   area.
4. **WI-025** (shared-user pip-install drift) is the only Profile A/B
   non-pass row and is in_human_review. It's Gate 4 scope but worth watching
   because it affects the upgrade journey.

## Gaps to flag

- **agent-notes CI still doesn't run mypy** (flagged by the 2026-07-25
  glm-5.2-2 reflection, still open). The family convention is mypy --strict;
  agent-notes is silently off-convention.
- **The plan status paragraph is getting long.** At four gates of history
  it's becoming a changelog embedded in a plan. Consider splitting completed
  gate evidence into a separate ledger file.
- **dossier notification preferences are instance-local** (file-backed).
  Correct for single-replica v1 but will silently split prefs under k8s
  multi-replica. Documented, not hidden, but worth a Plan 019 reminder.
- **The untracked `reflections/2026-07-20-qwen3-8-max-preview.md`** in
  agent-suite is still untracked (flagged by two prior sessions). Decide:
  commit or gitignore.
