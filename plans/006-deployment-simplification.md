# Plan 006 — Deployment simplification (from the mvmhermes01 dogfood)

**Status:** Proposed 2026-07-10.
**Author:** Claude (GLM 5.2), from the Plan 004 dogfood deployment on mvmhermes01
**Strategic role:** The first real deployment surfaced 7 bugs (all fixed) and 6
remaining friction points that would trip a new collaborator. This plan closes
them so deployment is a 5-command sequence, not a debugging session.

## Ground truth (verified 2026-07-10 on mvmhermes01)

After the 7 direct fixes (regista `ok` field, suite.env auto-loading, packaging
for skills/integrations, PyNaCl as core dep, bootstrap CLI fixes, doctor JSON
parsing, key_watch unsupported detection), the doctor reports:

```
regista: OK
agent-notes: failed (1 pre-existing data fail — links_audit)
agent-provenance: OK
lock: matches
```

The remaining friction is in 6 areas — each is a small, bounded fix.

---

## WI-1 — Bootstrap should use PRINCIPAL_ID from suite.env

**Problem:** The bootstrap's `provision` step defaults the principal to
`suite-service` (hardcoded in `bootstrap.py:331`). But the operator's
`PRINCIPAL_ID` is already in suite.env. The bootstrap provisions the wrong
principal, and the operator has to provision their real one separately.

**Fix:** Pass `os.environ.get("PRINCIPAL_ID")` through `run_bootstrap` to
`_step_provision`, defaulting to `suite-service` only when unset.

**AC:** `agent-suite bootstrap` with `PRINCIPAL_ID=alice` in suite.env
provisions the `alice` principal, not `suite-service`.

## WI-2 — agent-notes should auto-load suite.env

**Problem:** `agent-notes doctor` and `agent-notes install-harness` don't
auto-load suite.env — the operator must manually `source` it first. The
agent-suite CLI does auto-load (via `config.py`), but each component CLI
needs its own loader. agent-notes has a `suite_env.py` module but only
`RegistaConfig` uses it; `resolve_dsn` now falls back to suite.env (fixed)
but the process env still isn't populated.

**Fix:** Call `load_suite_env_into_environ()` at the top of agent-notes'
CLI `main()`, same pattern as agent-suite's `config.py`.

**AC:** `agent-notes doctor` works without manual `source suite.env` — it
reads DSNs and config from the suite.env file automatically.

## WI-3 — Dangling links cleanup command

**Problem:** `agent-notes doctor` reports `links_audit: fail` when there are
dangling links (memory-to links pointing at deleted entities). This is a
pre-existing data issue in the shared store (11 dangling links on
mvmhermes01). It blocks `suite_ok: true` and there's no command to fix it.

**Fix:** Add `agent-notes links cleanup --dry-run` that identifies and
optionally removes dangling links. The doctor check should distinguish
"fixable data quality" from "broken state."

**AC:** `agent-notes links cleanup --dry-run` lists dangling links;
`agent-notes links cleanup` removes them; after cleanup, `links_audit`
passes.

## WI-4 — AGENT_NOTES_REGISTA_WRITES should default to true

**Problem:** `AGENT_NOTES_REGISTA_WRITES` defaults to `false`. An operator
who installs agent-notes and sets up suite.env but doesn't know about this
flag will see `writes_enabled: false` and wonder why breadcrumbs aren't
writing to regista. The flag was designed as a safety gate, but in practice
it's a trap — the operator already opted in by setting the DSN.

**Fix:** Default to `true` when a DSN is present (either `AGENT_NOTES_DSN`
or `REGISTA_DSN` from suite.env). The env var still overrides — set
`AGENT_NOTES_REGISTA_WRITES=0` to explicitly disable.

**AC:** With a DSN in suite.env and no `AGENT_NOTES_REGISTA_WRITES` set,
`agent-notes doctor` reports `writes_enabled: true`.

## WI-5 — cairn content_encryption warning should not block suite_ok

**Problem:** cairn's doctor reports `ok: true` but the `content_encryption`
check warns ("Content encryption is ON but no content key configured").
The text-mode doctor renders this as "degraded," which is confusing —
content encryption is a v2 feature (Plan 010), not a deployment
requirement. A Tier 0–1 deployment without content capture should be
fully green.

**Fix:** The `content_encryption` check should be `skip` (not `warn`) when
no content key is configured and content capture is not in use. The warn
status should only appear when the operator has explicitly enabled content
capture (`CAIRN_CONTENT_CAPTURE=1`) without a key.

**AC:** `agent-suite doctor` on a Tier 0–1 deployment with no content key
shows cairn as `OK`, not `degraded`.

## WI-6 — Deployment guide: one-command install script

**Problem:** The deployment guide (`docs/deployment-guide.md`) documents 10+
manual steps. A new collaborator following it will make mistakes. A script
that automates the repetitive parts (install components, create suite.env
template, run bootstrap, generate lock) would reduce onboarding to one
command + a few decisions.

**Fix:** `scripts/deploy.sh` (or a `agent-suite deploy` subcommand) that:
1. Checks prerequisites (Python, uv, Postgres reachable)
2. Installs the 4 core components via uv
3. Writes a suite.env template (with placeholders for passwords)
4. Runs `agent-suite bootstrap --dry-run` and shows the plan
5. Waits for confirmation, then runs `agent-suite bootstrap`
6. Runs `agent-suite lock` and `agent-suite doctor`

**AC:** A new collaborator runs one script, fills in 3 values (DSN, key
path, principal), and gets a green doctor. The script is idempotent and
safe to re-run.

---

## Sequencing

WI-1 and WI-2 are small, independent code fixes — do them first. WI-3 and
WI-4 are agent-notes changes. WI-5 is a cairn change. WI-6 depends on
all the above being fixed (the script assumes they work). All can be done
in parallel.
