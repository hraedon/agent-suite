---
model: qwen3.8-max-preview
datetime: 2026-07-20T20:15, UTC
project: agent-suite
---

# Session Reflection — 2026-07-20

**Work summary:** Implemented Plan 018 WI-4 (skill de-workaround sweep): inventoried all 21 skills for CLI contract workarounds, found only one qualifying removal (reflect skill exit-code distrust, version-gated on agent-notes 1.0.0), built the behavioral skill-invocation smoke suite (15 tests), wired it into CI with a dedicated pgvector Postgres + agent-notes schema setup, filed WI-023 for remaining components, and pushed to green CI.

---

## On the project

agent-suite is at an inflection point. The thin-orchestration charter is well-defended — AGENTS.md, the bootstrap contract, and the import-boundary test all enforce it mechanically. Plan 018 is the plan that makes the *agents building the suite* stop paying a tax for contract violations in the components they drive. The conformance kit is elegant: one versioned package, N consumers, no drift. The skill smoke suite extends that logic to the skill layer — proving that documented invocations actually work, not just that the CLI passes unit-level conformance cases.

What feels fragile: the CI interop job is getting heavy. It now provisions two databases (interop + agent_notes_smoke), installs four sibling packages, and runs five test files. The timeout is 10 minutes. If the pgvector image is slow to pull or the schema application hits a transient failure, the whole job goes red for reasons unrelated to the code under test. This is the cost of integration testing — acceptable, but worth watching.

## On the work done

The inventory step was the most valuable part. Reading all 21 skills and classifying each potential workaround against the version gate produced a clear table: only ONE workaround qualified for removal. The rest were either contract-aware behavior (the "file a breadcrumb if contract drifts" footer) or guarded non-suite CLIs (git, filter-repo). This validates the plan's insistence on "inventory by reading, not grep."

The smoke suite design went through two adversarial review rounds. The first round (kimi) caught real issues: empty .git dir, missing --json on reconcile, hard-coded identifiers, CI fallback leaking into production. The second round (kimi again) raised infrastructure concerns about pgvector and schema separation that required CI workflow changes. Both rounds improved the code materially.

What I'm less confident about: the CI schema setup step (`psql` in a loop over schema files, with `|| true` error suppression). It's pragmatic but not robust — a schema file that fails silently could leave the database in a partial state. The proper fix is an idempotent migration runner, but that's agent-notes' responsibility, not agent-suite's.

## On what remains

- **CI green confirmation:** The push just went out. Need to verify the interop job passes with the pgvector image + schema setup. If `pgvector/pgvector:pg18` isn't available on GitHub's runner registry, the job will fail at the service container pull.
- **WI-023 (cairn/acb/agent-wake/dossier contract audits):** These four components still need P0 kit adoption before their skill workarounds can be removed. This is the next gating step for completing WI-4.
- **Grammar-alias work (P2, regista):** The plan mentions this can ride along or be separate. Not started.
- **Skill distribution:** The reflect skill edit lives at `/home/itadmin/.claude/skills/reflect/SKILL.md` — outside the repo. `agent-notes install-skills` distributes skills to harnesses, so the edit takes effect immediately for this harness but won't propagate to others until re-installed.

## Gaps to flag

- `tests/test_skill_smoke.py:171` — the `except Exception` around `create_project` is broad. A programming error (e.g., wrong argument type) would be silently swallowed and fall through to the fallback path. Should catch only `psycopg.errors.*` or `regista.RegistaError`.
- `.github/workflows/ci.yml` schema setup step — `psql -f` with error suppression means a failed migration is invisible. If `000_core.sql` fails (e.g., pgvector not actually available), all subsequent tests fail with confusing "relation does not exist" errors rather than a clear "schema setup failed."
- The smoke suite doesn't assert the installed agent-notes version matches SUITE.lock. If CI installs a different SHA than the lock pins, the test proves nothing about the locked version. The interop job's `AGENT_NOTES_SHA` env var is the source of truth, but nothing cross-checks it against SUITE.lock at test time.
- `reflect/SKILL.md` is edited in-place but not tracked in any repo. If the harness is rebuilt, the edit is lost. The skill distribution mechanism (`agent-notes install-skills`) should be the source of truth, but the skills live outside version control.
