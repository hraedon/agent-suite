---
model: qwen3.8-max-preview
datetime: 2026-07-25T21:45 UTC
project: agent-suite
---

# Session Reflection — 2026-07-25

**Work summary:** Resolved all six P0 findings from Sol's review (dossier key rotation fencing, release truth repair, lock enforcement, identifier gate strict mode, work-item reconciliation hardening, agent-notes typing gate), then began Plan 015 Gate 1 implementation (provider contracts + golden journey tests for GJ-1–GJ-4 in dossier). Five repos touched: agent-suite, dossier, agent-notes, agent-provenance, agent-wake.

---

## On the project

The suite's architecture is genuinely well-designed — the thin-orchestration charter, the probe-emitted feature matrix, the lock-agreement model. The discipline of "compose via CLIs, never reimplement" is visible everywhere and it pays off: changes stay contained. The release board as a machine-readable gate sequence is elegant.

What feels fragile is the truth-maintenance burden. The feature matrix, claims ledger, release board, and plan documents all carry overlapping state that drifts independently. The probes help, but the notes/proof fields still require manual reconciliation. The `_WI_ASSIGNMENTS` dict in feature-matrix.py is a second source of truth that can diverge from the JSON. This session found exactly that: the JSON said one thing, the generator said another, and the test caught the gap.

The dossier codebase is clean and well-factored. The implicit provider pattern (area modules as pure functions over the gateway) is a good design that just needed formalization. The route-ordering bug (/knowledge/new shadowed by /{note_id}) is the kind of thing that only a behavioral test catches — structural probes would never find it.

## On the work done

The P0 fixes are solid and well-tested. The lock_agreement extension (identity validation, strict mode, MISSING_LOCK/IDENTITY_MISMATCH statuses) is the change I'm most confident in — it's pure, stdlib-only, and the tests are comprehensive.

The dossier key rotation fencing is correct but I'd want a second pair of eyes on the error code choice (SECRET_WRITE_UNSUPPORTED). It works because the app.py handlers now surface exc.message, but the semantic mismatch (it's not about secret writes, it's about a disabled operation) could confuse future debugging. A dedicated error code would be cleaner but requires a regista change.

The Gate 1 provider contracts are a foundation, not a completion. The Protocols match the gateway's actual API surface (I renamed from idealized names to real ones), which is pragmatic but means the contracts document what IS rather than what SHOULD BE. The golden journey tests found two real bugs (route ordering, reserved transition) which validates the approach.

The agent-notes git_reconcile project-scope fix is conservative — it only rejects matches with a *different* project prefix, not unqualified matches. This prevents false closures without breaking the common case where commits don't use project prefixes.

## On what remains

**Needed before Gate 1 can close:**
1. Knowledge module fix: `create_note` uses reserved transition "created" via `append_note_event` — needs to use `create_work_item` or a non-reserved transition. This blocks GJ-3 golden journey completion.
2. WI-1.2 negative cases: same-lineage, missing-lineage, expired-claim, stale-form. These are the separation-of-duties edge cases that Plan 015 explicitly requires.
3. WI-1.3 through WI-1.6: activity/evidence journeys, identity/keys tests, notification tests, accessibility qualification. Each is substantial.

**Needed before the P0 work is fully closed:**
4. The three stale "high" work items (agent-notes WI-022, cairn BC-016, ACB WI-013) need to be formally closed in the tracker — I identified them but didn't transition them.
5. The agent-notes mypy burn-down (119 errors) — the gate is established but non-blocking.
6. The 33 mutable GitHub Action references across constituent workflows need SHA pinning.

**Sequencing:** Knowledge module fix → WI-1.2 negative cases → WI-1.3/1.4 (can parallelize) → WI-1.5/1.6.

## Gaps to flag

- `dossier/src/dossier/knowledge.py:167` — uses `transition="created"` which regista now blocks as reserved. The xfail in test_golden_journeys.py marks this, but it means knowledge creation is broken against real regista, not just in tests.
- `dossier/src/dossier/gateway.py:98-121` — `describe_work`/`describe_identity` use deferred imports inside the method body to avoid a circular import. This works but is unusual; a top-level TYPE_CHECKING import handles the annotation but the runtime import is still deferred.
- `agent-suite/scripts/feature-matrix.py:124` and `feature-probes.py:2205` — both define the WI assignment summary independently. If they diverge, the test_committed_json_matches_generator test catches it, but the dual definition is a maintenance risk.
- `agent-notes/src/agent_notes/core/git_reconcile.py` — the `_is_foreign_project_match` regex uses a negative lookahead for the project slug but doesn't anchor to word boundaries on the left of the slug. A slug like "agent" would not match "agent-notes:WI-022" as foreign, which is correct, but "my-agent:WI-022" would also not be flagged as foreign for project "agent". Edge case, low risk.
- `agent-wake/SUITE.lock` — newly created minimal lock with no [spine]. If agent-wake ever gains a regista dependency, this file needs a [spine] block added.
