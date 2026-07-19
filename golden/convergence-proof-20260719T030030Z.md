# Convergence Proof Summary — agent-suite pinned clean-install (rerun)

**Date:** 2026-07-19T03:00:30Z
**Scope:** Profile A/B smoke proof — tier-0/1 spine + faces; tier-2 (agent-wake) absent; codex CLI absent
**Verdict:** PARTIAL CONVERGED — Profile A/B smoke

## Context

This is a rerun of the convergence proof against the exact repinned candidate
(SUITE.lock at agent-suite main HEAD). It addresses Sol's review finding #3
(2026-07-19): the prior proof overstated its verdict as "CONVERGED" while its own
evidence recorded absent agent-wake, failed codex operations, an unhealthy suite
doctor, lock drift, and skipped onboarding. The prior proof also used editable
source checkouts rather than immutable candidate artifacts.

The prior proof log was moved to `golden/local/` (gitignored). This document is the
scrubbed, publication-clean summary. The full detailed log with operator-specific
commands, exit codes, and outputs lives at `golden/local/convergence-proof-<ISO>.md`
(gitignored — contains real hostnames and infrastructure details not for the public tree).

## Pinned revisions (from SUITE.lock)

| Component | Version | Installed |
|-----------|---------|-----------|
| regista | 0.5.1 (schema 43, workflow 2, envelope 5) | yes |
| agent-notes | 1.0.0 | yes |
| agent-provenance (cairn) | 0.1.0 | yes |
| agent-capability-broker | 0.1.0 | yes (CLI; doctor fails — no manifest) |
| dossier | 0.0.1 | yes |
| agent-wake | 0.1.0 | no (no Node runtime on proving host) |
| agent-suite | 0.0.1 (main HEAD) | yes |

**Install path caveat:** editable source checkouts (`pip install -e`) at pinned SHAs
via `git worktree add --detach`, NOT immutable wheel artifacts from PyPI. This is a
known gap (Sol's finding #2 — regista is not on PyPI; the candidate is not yet
publishable). The install path is appropriate for a development proof but does not
exercise the published-package install path that a real deployment would use.

## Per-step verdict

| Step | Verdict | Notes |
|------|---------|-------|
| 1. Setup | PASS | Isolated HOME, pgvector PG container, venv on root FS |
| 2. Install | PASS | 6 Python components at pinned SHAs; agent-wake skipped (no Node) |
| 3. Bootstrap | PASS | All tier 0-1 steps done; user_onboarding skipped (not implemented) |
| 4. Onboard | PASS | Idempotent (already_done) |
| 5. Codex install | HONEST FAILURE | codex CLI not installed (expected) |
| 6. Doctor + lock --check | PASS (degraded) | lock --check and doctor AGREE (Sol #1 fixed); tier-2 named gaps |
| 7. Work/knowledge | PASS | Work item filed + memory retained; required manual schema migration + vocab seeding |
| 8. Provenance | PASS | 1 event exported + cryptographically verified (ed25519); required manual regista provisioning |
| 9. Reinstall/no-op | PASS | Idempotent (provision + harness already_done) |
| 10. Uninstall | PARTIAL | Harness uninstalls worked; bootstrap has no --uninstall; PG torn down |

## Sol finding #1 verification — doctor.lock vs lock --check agreement

The prior false-green (doctor reported a green lock while `lock --check` detected
drift) is fixed. Both commands now use the same `check_drift` with
`current_provider_extension` probed via `read_provider_extension()`:

```
doctor.lock.matches:  False, 3 drifts
lock --check.matches: False, 3 drifts
doctor drift:  [(acb, component_missing), (agent-wake, component_missing), (memory_provider, provider_drift)]
lock drift:    [(acb, component_missing), (agent-wake, component_missing), (memory_provider, provider_drift)]
AGREE: True
```

## Named gaps (why this is PARTIAL, not CONVERGED)

1. **agent-wake absent** — no Node.js runtime on the proving host. Tier-2 (plumbing)
   component, optional for the core suite.

2. **codex CLI absent** — codex-plugins install/uninstall fail honestly. Codex is an
   explicit candidate target until all required component adapters pass conformance.

3. **acb doctor failed** — no `capabilities.toml` manifest configured. Tier-2 (plumbing),
   optional for the core suite. The acb CLI IS installed (version 0.1.0) but needs a
   manifest to report healthy.

4. **Lock drift (3)** — acb absent, agent-wake absent, memory_provider provider_drift
   (lock pins hindsight; proof used native — no hindsight instance available). All
   drift is named and honest. doctor and lock --check agree on the drift set.

5. **user_onboarding not implemented** — bootstrap's USER_ONBOARDING step returns
   SKIPPED ("not yet implemented — Plan 001 WI-3.3"). Known scaffolded step.

6. **dossier failed** — missing session_secret and auth_backend config. No suite.env
   was provided (process env only). Expected for a synthetic proof.

7. **cairn content_encryption warning** — content encryption ON but no content key
   configured. Expected for a synthetic proof.

8. **Editable source checkouts, NOT immutable wheel artifacts** — Sol's finding #2.
   regista is not on PyPI; the candidate is not yet publishable. The install path was
   `pip install -e` from git worktrees at pinned SHAs.

## Bootstrap integration gaps discovered

These are gaps where the bootstrap "faces" step does not fully wire agent-notes for
operation. Each required a manual step to proceed:

1. **Schema migration not run by bootstrap** — the bootstrap "faces" step installs the
   harness targets but does NOT run `agent_notes.scripts.migrate --all`. The schema
   migration must be run manually before `agent-notes init` can register a project.

2. **Vocabularies not seeded by bootstrap** — wi_kind, wi_status, wi_severity, and
   memory_type vocabularies are empty by default. Must be seeded manually before work
   items or memories can be filed.

3. **Regista face project mapping not configured by bootstrap** — agent-notes resolves
   its regista project from the repo path, which doesn't match the bootstrap-provisioned
   project. Must manually provision the matching regista project and enable
   `AGENT_NOTES_REGISTA_WRITES=1` for the attestation path to work.

These gaps do not block the Profile A/B smoke proof — each has a manual workaround — but
they should be addressed in the bootstrap before the full convergence proof can run
hands-off.

## Uninstall coverage

- **codex-plugins uninstall:** honest failure (no codex CLI — expected).
- **cairn uninstall-harness:** removed all cairn hooks + env vars from harness settings.
- **agent-notes install-harness --uninstall:** removed skills + harness manifest file.
- **bootstrap --uninstall:** does not exist. The bootstrap layer provides no reverse
  operation for provision, schema migration, or project registration.
- **PG container:** torn down (`docker stop`), destroying all DB state (regista projects,
  agent-notes schema, work items, memories, events).

**What remains on disk after uninstall:**
- venv (not cleaned by any uninstall step)
- source checkouts at pinned SHAs (not cleaned)
- isolated HOME (harness wiring removed; keys + config remain)
- agent-suite main HEAD checkout

## Environment notes

- **Python 3.14** (not 3.12 as family CI targets) — all components work correctly on 3.14.
- **Isolated HOME on tmpfs, venv on root FS** — tmpfs was too small for pip installs;
  venv + source checkouts placed on root FS. Same isolation principle, different layout.
- **Separate agent_notes database** — agent-notes requires its own database (schema
  conflict with regista's public.projects table). Created in the same PG container.
- **pgvector** — the `pgvector/pgvector:pg16` image is required (agent-notes schema uses
  the vector extension). Standard `postgres:16` lacks it.

## Reference

- **Detailed local log:** `golden/local/convergence-proof-20260719T030030Z.md` (gitignored —
  operator-specific, contains real hostnames and infrastructure details).
- **Prior proof (relabeled):** `golden/local/convergence-proof-20260718T232221Z.md` (gitignored —
  the prior run that Sol's finding #3 flagged for overstatement).
- **SUITE.lock:** the repinned candidate at agent-suite main HEAD.
