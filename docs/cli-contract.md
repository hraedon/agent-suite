# CLI Contract v1

**`cli_contract_version = 1`** — normative for every suite CLI
(agent-suite, regista, agent-notes, dossier, cairn, acb, agent-wake's
CLI verbs). Plan 018 WI-1. A component "implements CLI contract v1"
when the conformance kit (§7) runs green against it in its CI.

The CLI is the suite's agent API. Agents drive it programmatically
across harnesses; every deviation from this contract becomes a
defensive workaround in a skill, silently copied forever. The contract
is deliberately one page: violations are bugs, not style choices.

## 1. Stream discipline (P0)

- Under `--json`: stdout carries **exactly one JSON document** (or one
  NDJSON stream where the verb documents it) and nothing else. All
  logging, progress, warnings, and diagnostics go to stderr.
- Without `--json`: human-readable output goes to stdout; diagnostics
  still go to stderr.
- No library may write to stdout as a side effect (structlog,
  deprecation warnings, pip noise). If a dependency logs, it logs to
  stderr.

## 2. Exit-code taxonomy (P0)

| Code | Meaning |
|------|---------|
| `0` | Success. Also: honest reports of bad *subject* state (a doctor that finds problems ran successfully) unless the verb documents `--exit-code`. |
| `1` | Operational failure — **every** path that reports an error. No path may print an error and exit 0. |
| `2` | Usage error (argparse default: unknown verb, missing required flag). |

**The 1/2 boundary is who detects it, not whose fault it is.** Exit `2` is
reserved for failures the argument *parser* raises (unknown verb, missing
required flag, bad flag value rejected by the parser) — those print usage text,
not the envelope. A flag combination or value the parser accepts but the verb
then rejects (e.g. `FLAG_CONFLICT`, `FLAG_INVALID`) is a documented error path:
envelope on stdout, exit `1`. The conformance kit enforces this split — an
envelope path that exits `2` is a violation (ratified 2026-08-05, WI-071 L4).

Partial success must pick a side: a batch verb that fails any item
exits nonzero and reports the split in the error envelope's `partial`
field (§3). "Some succeeded" is not exit 0.

**Dry-run is success (WI-021, ratified 2026-07-20).** A `--dry-run` that
successfully computes and prints its plan exits `0` — it ran correctly and
acted on nothing, which is the contract for `0`. "Nothing was applied" is
carried by the plan's *output* (which states it would act and did not) and by
the flag the caller passed, never by a distinct exit code. A verb that
genuinely needs to fail loudly when a caller forgot `--apply` (e.g. a
production `bootstrap` gated in CI) uses the same documented `--exit-code`
opt-in as the doctor row above; it is per-verb and off by default, so no
sibling is required to implement it. A dry-run that *fails to compute its plan*
is an ordinary error and exits `1`.

## 3. Error envelope (P0)

Under `--json`, every error path emits this envelope as the single
stdout document, alongside the nonzero exit — consumers get one parse
path for both outcomes. Schema: `data/cli-error-envelope.schema.json`.

```json
{
  "ok": false,
  "error": {
    "code": "WI_KIND_UNKNOWN",
    "message": "Unknown wi_kind 'bugg'",
    "detail": "Valid kinds: bug, todo, rfc, question",
    "retryable": false,
    "partial": null
  }
}
```

- **`code`** — stable, SCREAMING_SNAKE, grep-able. Codes are API
  surface: renaming or removing one is a breaking change. Adding one is
  not.
- **`message`** — one human line. **Not** API surface; agents must not
  parse it.
- **`detail`** — remediation or specifics; may be `null`. Not API
  surface.
- **`retryable`** — `true` only for transient infrastructure failures
  (connection refused, lock contention). Caller errors are `false`.
- **`partial`** — `null`, or `{"succeeded": n, "failed": m, "items":
  [...]}` for batch verbs that document partial success. Non-null
  `partial` still exits nonzero.
- **Redaction:** error output never carries secret material. Reference
  the *name* of an offending field or env var, never its value.
- Success documents are the verb's own shape; `{"ok": true, ...}` is
  recommended but not required for v1 (existing success shapes are
  grandfathered).

Without `--json`, error paths print `error: <message>` (and optionally
detail) to **stderr**, never stdout, with the same exit code.

## 4. Grammar conventions (P2 for existing surfaces, P0 for new ones)

- `noun verb` order for **new** surfaces (`work-item file`, `bundle
  verify`). Existing grammar is preserved through aliases with a
  deprecation window of at least one minor release before removal.
- Entity identifiers are positionals; options are kebab-case flags.
- `--json` exists on every verb whose output an agent might consume.
- Tracebacks are bugs on documented error paths: catch, map to the
  envelope, exit nonzero. (Tracebacks on *undocumented* crashes are
  acceptable — they are what distinguishes a crash from an error.)
- `SIGPIPE`/broken stdout (e.g. `| head -1`) must not traceback.

## 5. Output honesty (P1)

The output format matches what the name or extension implies. A verb
asked to write `out.tar.gz` either writes a gzipped tar or refuses; it
never silently writes JSON under a lying name (the regista WI-210
class).

## 6. Contract discovery — the CLI manifest (P1)

Each conforming CLI ships a machine-readable manifest:

- `<tool> contract --json` emits it at runtime;
- `data/cli-manifest.json` in the component repo commits it.

Manifest fields: `cli_contract_version`, `manifest_schema_version`,
and per-command: name, aliases, mutability (`read-only` | `mutating`),
`json` (bool), framing (`document` | `ndjson`). The conformance kit
discovers what to test from the manifest, and SUITE.lock records each
component's implemented contract version — the gate for removing
skill-side workarounds (Plan 018 WI-4).

## 7. Conformance

The kit is one centrally versioned package owned by agent-suite
(`agent_suite.conformance`) — components consume it pinned, never
copied, so there is exactly one kit version to drift from. It runs in
two lanes: source checkout (per-PR) and built wheel installed into a
clean venv (release tags). Results per component are recorded in
agent-suite's `data/cli-conformance.json`, not in the frozen v1
feature matrix.

### Meta-guard — a gate that skips enforces nothing (WI-026)

A conformance gate's failure mode must not be "silently passes." The
2026-07-24 bug: three components' `test_cli_conformance.py` did
`pytest.importorskip("agent_suite.conformance")` against a module name
that was never installed, so every case *skipped*, CI stayed green, and
zero contract was enforced. A skipped gate is indistinguishable from a
passing one in a green build.

The cure is defense in depth. Both layers ship from the kit; every
conforming component adopts both:

1. **Empty-dimension guard (kit helper).** After the kit import, call
   `assert_cases_declared(success=..., error=..., usage=..., minimum=1)`
   once at module top. It raises `ConformanceGateError` at collection
   time if any named case group is short of `minimum` — catching the
   "module loaded but a refactor emptied a dimension" class. It also
   refuses a no-arg call (a guard over no dimensions protects nothing).

2. **Whole-module-skip guard (meta test).** Add a
   `test_conformance_meta_guard.py` (see agent-suite's for the reference
   shape) that runs the conformance module as a subprocess and asserts
   ≥1 case *passed*, not all-skipped. This is the only layer that
   catches `importorskip` firing against a missing/wrong kit module,
   because the importorskip'd module never reaches layer 1. The guard is
   factored into a pure `require_gate_ran(pytest_output)` function with a
   deny-case, so it is provably not a tautology over string matching.

`importorskip` remains the right primitive for a *local, kit-less
checkout* (a dev who skipped the `[dev]` extra should not get a hard
error). In CI the kit is a mandatory pinned dep; layer 2 turns "CI ran
with the kit absent/wrong-named" from a silent skip into a red build.

## Decision record — CLI over MCP

Per `docs/process-calibration.md` §1: the suite keeps a CLI-first agent
surface (cross-harness, guardable via permission modes, attestable via
cairn command-boundary evidence) instead of migrating to typed MCP
tools, and buys back MCP's by-construction rigor with this contract
plus mechanical conformance. **Falsifier that reopens the decision:**
harness-level MCP interposition (guarding + attestation of MCP calls)
plus lazy tool loading plus standardization on a single harness. None
of the three holds today (2026-07-20).
