---
model: qwen3.8-max-preview
datetime: 2026-07-24T14:20 UTC
project: agent-suite
---

# Session Reflection — 2026-07-24 (B3 completion + the skip-bug)

**Work summary:** Completed Plan 018 P2 / Plan 019 B3 by adopting the conformance kit in agent-wake (the last component), and — more importantly — discovered and fixed a family-wide bug where cairn/acb/dossier's conformance gates were silently *skipping* in CI because they imported the wrong module name. Five repos committed: agent-wake (new adoption), cairn/acb/dossier (import fix), agent-suite (conformance records). Verified live on mvmhermes01.

---

## On the project

The CLI-contract-v1 initiative is the suite's best idea: one page of normative contract, one centrally versioned kit, mechanical enforcement. The architecture is sound and the family discipline (envelope on stdout, exit taxonomy, no tracebacks) is genuinely consistent across components now that I've seen five of them up close.

But this session exposed the initiative's central fragility: **the enforcement was, in three of six components, not actually enforcing anything.** The conformance tests existed, were "merged green," and were recorded as adopted — yet they `importorskip`'d a module that was never installed, so they skipped on every CI run. A skipped gate is indistinguishable from a passing one in a green build. This is precisely the "fails open" hazard WI-018 names, and it survived because nobody ran the test *locally with the kit installed* after the B1 module rename. The lesson isn't "be more careful" — it's that a conformance suite needs a meta-guard: something that fails if the conformance test *collects zero cases*. `pytest.importorskip` is the wrong primitive for a mandatory gate; it's designed for optional deps, and here the dep is mandatory.

## On the work done

The agent-wake adoption is clean and I'm confident in it: 368 tests pass, mypy --strict clean, the three conformance cases genuinely run (not skip) and pass. The envelope boundary mirrors acb's proven pattern exactly. The one judgment call I'd want a second opinion on: I made the dev dep conditional (`python_version >= '3.12'`) rather than bumping the daemon off 3.11. This keeps 3.11 runtime support but means the conformance gate only runs on the 3.12 CI lane — a 3.11-only regression in the error path wouldn't be caught. cairn just dropped 3.11 entirely; agent-wake may want to do the same, but that's a separate decision I didn't want to force.

The skip-bug fix is the higher-value work and I'm confident it's correct: I verified each of cairn/acb/dossier *passes* (not just runs) after the import change, in a venv with the kit installed. The cairn case was a good scare — it failed locally, but only because my long-lived local venv had a *stale console script* pointing at `cairn._cli:main` instead of `cli_entry`; a fresh `pip install -e .` (what CI does) fixed it. In CI the script is always fresh, so cairn passes there.

## On what remains

1. **Push the four in-sync repos** (agent-wake, cairn, acb, dossier) and watch CI — the fixes only land once pushed, and I want to see the gates actually go from "skip" to "pass" in real CI. I committed but did not push (the family works via PRs; that call is the operator's).
2. **Reconcile agent-suite's divergence** (see Gaps). This blocks pushing agent-suite and is the single most important loose end.
3. **A meta-guard against empty conformance collection** — the structural fix for the skip-bug class. Either assert `len(collected_cases) > 0` in each `test_cli_conformance.py`, or have the kit ship a `assert_cases_declared()` helper. Without this, the next module rename silently re-breaks the gates. File as a WI under agent-suite.
4. **agent-wake 3.11 vs 3.12** — decide whether to drop 3.11 (like cairn) so the conformance gate covers the whole support matrix.

## Gaps to flag

- **agent-suite local main is diverged from origin (ahead 3 / behind 3) and I did NOT push it.** Local carries Paul Merritt's unpushed Plan 019 B1 extraction (`a30a1d7`, creates `packages/agent-suite-conformance/`) + reflection + my `data/cli-conformance.json` commit. origin/main carries the WI-025 fix (`921c2e7` "make runtime upgrades provenance-aware", merged as PR #46 = `8c7bcae`) + a feature-probes reproducibility fix. **The WI-025 fix is NOT in the local checkout** — `src/agent_suite/upgrade.py` still only does `pipx upgrade`. Whoever reconciles must merge B1 (unpushed) with WI-025 (origin) and check `data/cli-conformance.json` (both B1 and I touched it; origin didn't). This is a human/PR decision, not an agent auto-merge.
- **mvmhermes01 is drifted and running pre-WI-025 agent-suite.** `agent-suite doctor --json` → `suite_ok: false`; deployed regista is **0.5.0** (schema 41 / envelope 4) vs the locked **0.5.3** (schema 43 / envelope 5); dossier absent; agent-notes failed a check. `agent-suite upgrade --dry-run --component regista` still proposes `pipx upgrade regista` and `--check` says "no advancements available" — i.e. the box has NOT been upgraded to the WI-025-fixed agent-suite (it's a uv-tool install at `~/.local/share/uv/tools/agent-suite`). The WI-025 work item claims live proof of reconciling a *user-pip* install; mvmhermes01's agent-suite is a *uv tool*, a different topology — worth confirming the fix covers uv-tool installs too, not just user-pip. I did not mutate the live box.
- **The stale-console-script landmine.** A long-lived editable venv keeps an old console script after an entry point changes (cairn's pointed at `main` not `cli_entry`). Anyone verifying conformance locally must `pip install -e .` first or they'll test the wrong boundary and get a false negative. CI is immune (fresh install).
- **`reflections/2026-07-20-qwen3-8-max-preview.md` is still untracked** in agent-suite (flagged by the 2026-07-24 B1 reflection too). Decide: commit or gitignore. I left it alone.
- **install-harness `--dry-run` = exit 2** is preserved as load-bearing in agent-wake and acb, but contract §2 (ratified 2026-07-20) says dry-run is success (exit 0). This is a deliberate, documented deviation pending live cred-skill validation — but it's a live contract inconsistency that needs its own pass, not perpetual deferral.
