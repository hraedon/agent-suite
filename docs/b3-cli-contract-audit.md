# B3 — CLI contract-v1 audit (Plan 019 B3 / WI-023)

**Status:** Audit complete 2026-07-21. Fixes sequenced below (not yet landed).
**Scope:** WI-023 = "Plan 018 P2: cairn/acb/agent-wake/dossier CLI contract audit
+ kit adoption." This is the **audit** half — an empirical measurement of each
component against CLI contract v1 (`docs/cli-contract.md`) using the published
conformance kit (`agent-suite-conformance==1.0.0`, Plan 019 B1) — and the
per-component fix plan it produces. Each fix lands as its own PR in its own repo,
mirroring the Plan 018 P0 adoptions in regista (PR #9) and agent-notes (PR #10).

## Method

Ran each component's real CLI and checked the four contract-v1 behavioral
invariants the kit encodes (`agent_suite.conformance.kit`):

- **§1 stream purity** — under `--json`, stdout is a single JSON document, nothing else.
- **§2 exit taxonomy** — success 0; usage error 2; operational error nonzero-but-not-2.
- **§3 error envelope** — a documented operational failure emits a valid envelope
  (`{"error": {"code": …}}`) on stdout in `--json` mode, with no secret leakage.
- **§4 robustness** — no Python traceback on any error path or on a broken stdout pipe.

Probes were read-only (help, an unknown verb, `doctor --json`, and — via source
inspection — the operational error paths), so nothing mutated a config or store.

## Findings

| Component (repo) | CLI framework | §1/§2 (usage 2, JSON success) | §3 error envelope | §4 traceback/pipe | CI Python | regista in CI |
| --- | --- | --- | --- | --- | --- | --- |
| **cairn** (agent-provenance) | click | ✓ (`doctor --json` clean; unknown verb → 2) | ✗ none — errors are click's human `Error: …` on stderr, no envelope | to verify per-path | **3.11** (off the 3.13/3.14 policy) | **`==0.5.1`** (drift vs SUITE.lock 0.5.3) |
| **acb** (agent-capability-broker) | argparse | ✓ (`doctor --json` clean; unknown verb → 2) | ✗ none | to verify per-path | 3.12/3.13/3.14 ✓ | none / clean |
| **dossier** | argparse | ✓ (unknown verb → 2) | ✗ none (the envelope-shaped code in `app.py` is the FastAPI web app's HTTP errors — a different surface from the CLI) | to verify per-path | 3.12/3.13/3.14 ✓ | **`==0.5.1`** (drift) |
| **agent-wake** | — | — | — | — | — | — |

**The shared gap is §3 only.** All three CLI components already satisfy §1/§2 —
their frameworks give usage-error-exit-2 and clean `doctor --json` for free. None
emits a contract-v1 **operational-error envelope**: on a documented runtime
failure in `--json` mode the contract wants a valid `{"error":{"code":…}}` on
**stdout** with exit 1, and today each emits a human error string (click's
`Error:` / argparse's message) instead. §4 (no traceback, broken-pipe) must be
verified path-by-path during each fix; no traceback was observed on the probed
paths.

**agent-wake is N/A.** It ships **no first-party CLI** (no `[project.scripts]`;
it is a cross-harness signaling daemon + MCP surface). CLI contract v1 does not
apply. Close this quadrant of WI-023 as N/A; revisit only if a CLI verb surface
is later added.

## Per-component fix plan (sequenced)

Each is one PR: add a contract-v1 error-envelope boundary on operational error
paths, adopt the kit as a normal dev/test dep (`agent-suite-conformance==1.0.0`),
add a `test_cli_conformance.py` parameterizing the kit's `SuccessCase` /
`ErrorCase` / `UsageCase` / `BrokenPipeCase` over the component's own verbs, and
fix whatever the kit surfaces. Adopt the kit **with** the fixes in the same PR
(the conformance test must be green when it lands, as in P0).

1. **acb — do first (cleanest).** argparse; CI is already on-policy (3.13/3.14)
   and carries no hardcoded regista pin. The *only* work is the §3 envelope +
   kit adoption. Establishes the argparse envelope pattern the others reuse.
2. **dossier — second.** argparse (same envelope pattern as acb). Keep the CLI
   envelope distinct from the web app's HTTP error surface. Also apply
   develop-against-lock (Plan 019 B2) while touching CI — kill the `==0.5.1` pin.
3. **cairn — last (largest).** click, not argparse, so the envelope boundary is a
   `main()` wrapper that converts `ClickException`/operational failures into an
   envelope on stdout (exit 1) while leaving `BadParameter`/usage at exit 2 — the
   boundary must be `--json`-aware. Also bump CI 3.11 → 3.13/3.14 and apply
   develop-against-lock (kill `==0.5.1`). Most surface area, most care.

## Why this ordering

The handoff (`handoff-plan019-b2b3.md`) says "sequence by dependency —
regista-adjacent first." Empirically the §3 gap is identical across all three, so
the differentiator is *incidental cost*, not contract distance: acb is clean CI +
one concern, dossier adds one B2 pin, cairn adds a framework difference + a CI
version bump + a B2 pin. Doing the cheapest first proves the envelope pattern on
the least-entangled component, then reuses it. Each landed fix also raises the
quality of the substrate B2-generalize will develop against.

## Relationship to B2

cairn and dossier hardcode `regista-hraedon==0.5.1` in CI while SUITE.lock pins
0.5.3 — the same develop-against-`main` drift the B2 pilot fixed in agent-notes
(PR #13). Fold the B2 `scripts/dev-install.py` + develop-against-lock convention
into the cairn and dossier fix PRs (they touch CI anyway); that is the first
increment of **B2-generalize**, done opportunistically alongside B3.
