# Plan 018 — CLI surface hardening: the CLI is an API contract

**Status:** Proposed 2026-07-19. **Amended 2026-07-20** per Sol review:
versioned manifest + contract discovery (WI-1), common error envelope
(WI-1.5), centrally versioned conformance package with wheel-based runs
(WI-2), per-repo defect table with owners and dependencies (WI-3),
version-gated skill migration with behavioral acceptance (WI-4),
separate conformance results artifact, and explicit P0/P1/P2 sequencing.
**Owner:** agent-suite owns the contract definition and the conformance kit
(the doctor-contract pattern, §2.4 of the blueprint: suite defines, each
component conforms). Each component owns its remediation in its own tracker;
this plan tracks the umbrella and the acceptance evidence.
**Origin:** owner directive 2026-07-19 ("I don't want you guys having to
work against or around the tools"), following the MCP-vs-skills-vs-API
assessment: the suite's CLI-first agent surface is correct for cross-harness
support, guardability, and attestation — but only if the CLI is held to API
discipline. Today it is held to discipline by convention, and agents pay a
recurring tax working around contract violations.
**Evidence (all hit live, 2026-07-19, one session):**

- regista structlog writes to stdout, so `--json` consumers must strip
  non-JSON lines (long-known; agent-notes WI-019 tracks a consumer-side
  workaround — the root cause is upstream);
- `agent-notes work-item file` prints `Error: Unknown wi_kind value` and
  **exits 0** (agent-notes WI-026) — the fail-open class: automation cannot
  detect the failure;
- invocation-grammar drift: `work-item update <identifier> --append-body`
  vs. sibling verbs' flag styles cost three failed invocations to discover;
- `regista bundle export` writes JSON while accepting a `.tar.gz` output
  name (regista WI-210) — output-honesty violation that misleads the
  artifact's third-party audience.

A typed-tool (MCP) surface eliminates these by construction; the suite's
answer is to get the same rigor without giving up the CLI's cross-harness,
guardable, attestable properties. This is a concrete slice of Plan 010
§15.2 (conformance kit), delivered early because the operators paying the
tax are the agents building everything else.

## 1. Outcome

An agent can drive every documented verb of every suite CLI with zero
contract workarounds: parse stdout as JSON without stripping, trust exit
codes without re-parsing stderr for `Error:`, and predict invocation
grammar from one page of conventions. The skills layer stops encoding
defenses against the tools it wraps.

## 2. Priorities (Sol review, ratified)

- **P0 — honesty of the machine surface:** stdout purity, correct exit
  codes, the shared error envelope, and the conformance runner proving
  all three. (WI-1 §1–2, WI-1.5, WI-2 runner, WI-3 P0 rows.)
- **P1 — discoverability and reproducibility:** contract
  discovery/versioning (the manifest), conformance runs against built
  wheels in isolated environments. (WI-1 manifest, WI-2 wheel lane.)
- **P2 — convention convergence:** grammar normalization for new
  surfaces, alias/deprecation machinery, skill workaround removal.
  (WI-1 §3, WI-4.)

P0 lands first in **agent-suite, regista, and agent-notes** (the three
CLIs agents drive hardest); remaining components follow.

## 3. Work items

### WI-1 — The CLI contract (`docs/cli-contract.md`) + versioned manifest

One page, normative, versioned (`cli_contract_version = 1`). Contents:

1. **Stream discipline.** Under `--json`, stdout carries exactly one JSON
   document (or one NDJSON stream where documented) and nothing else; all
   logging, progress, and diagnostics go to stderr. Without `--json`,
   human output goes to stdout, diagnostics still to stderr.
2. **Exit-code taxonomy.** `0` success; `1` operational failure (and every
   path that prints an error message); `2` usage error (argparse default).
   No path may print `Error:` and exit 0. Partial success must pick a side
   and document it (see the envelope's `partial` field, WI-1.5).
3. **Grammar conventions.** `noun verb` order is the convention for **new**
   surfaces; existing grammar is preserved through aliases with a
   deprecation window of at least one minor release (the §2.1 config
   pattern applied to verbs and flags). Entity identifiers as positionals;
   `--json` on every verb; kebab-case flags.
4. **Output honesty.** The output format matches what the name/extension
   implies; refuse or warn on mismatch (the WI-210 class).
5. **Machine-readable errors.** Under `--json`, errors are the common
   envelope (WI-1.5) on stdout with the nonzero exit — consumers get one
   parse path for both outcomes.
6. **Contract discovery: the CLI manifest.** Each conforming CLI ships a
   machine-readable manifest (`<tool> contract --json`, and a committed
   `data/cli-manifest.json` in its repo) declaring: contract version,
   manifest schema version, command list with aliases, per-command
   mutability (read-only vs mutating), JSON support, and output framing
   (single-document vs NDJSON). The conformance kit discovers what to
   test from the manifest instead of a hand-maintained verb list, and
   SUITE.lock can later record each component's implemented contract
   version (the WI-4 gate).

**Accept:** contract committed; each component's AGENTS.md links it; a
decision record per `docs/process-calibration.md` §1 records the
CLI-over-MCP surface decision with its falsifier (harness MCP interposition
+ lazy tool loading + single-harness standardization would reopen it).

### WI-1.5 — Common error envelope (P0)

One JSON error shape for every suite CLI, defined in the contract and
validated by the kit:

```json
{
  "ok": false,
  "error": {
    "code": "WI_KIND_UNKNOWN",        // stable, grep-able, never renamed
    "message": "Unknown wi_kind 'bugg'",  // human, one line
    "detail": "Valid kinds: bug, todo, rfc, question",  // remediation
    "retryable": false,                // transient vs caller error
    "partial": null                    // or {succeeded: n, failed: m, items: [...]}
  }
}
```

Rules: `code` is stable API surface (renaming is a breaking change);
`message`/`detail` are not (agents must not parse them); `retryable`
distinguishes transient infrastructure failures from caller errors;
`partial` is non-null only for batch verbs that document partial
success, and a non-null `partial` still exits nonzero. **Redaction:**
error output must never carry secret material — messages that embed
values embed the *name* of the offending field, not its content; the
kit's secret-leak fixture (WI-2) enforces this.

**Accept:** envelope schema committed in agent-suite (JSON Schema +
prose); regista, agent-notes, and agent-suite CLIs emit it on every
`--json` error path.

### WI-2 — Conformance kit (centrally versioned package)

A single, centrally versioned conformance package owned by agent-suite —
**not** copy-or-import (a copied kit produces divergent copies; Sol
review). Components consume it the way they consume the identifier gate:
a pinned dependency (`agent-suite[conformance]` extra or the vendable
single-file runner distributed by `sync-` script with a version stamp
the kit checks at runtime). One kit version, N consumers, no drift.

Checks, parameterized over the component's **manifest** (WI-1 §6):

- **Success paths:** `--json` stdout parses as a single JSON document
  (or documented NDJSON) with zero non-JSON bytes; `--help` exits 0 on
  every verb; read-only verbs are side-effect-free (mutability honesty).
- **Failure paths:** every documented error fixture (unknown enum value,
  unresolvable reference, missing required flag, malformed input file)
  exits nonzero with the envelope shape; usage errors exit 2; no
  traceback reaches the user on documented error paths (tracebacks are
  bugs, not error UX); error output contains no secret material
  (fixture plants a known sentinel secret in env/config and asserts it
  never appears in stdout/stderr).
- **Robustness:** broken-pipe on stdout (e.g. `| head -1`) exits without
  traceback; `--dry-run` verbs perform no writes; idempotent verbs
  (re-run with same args) succeed and report honestly; partial batch
  failure exercises the `partial` envelope field.

**Runs in two lanes:** (a) source-checkout lane in each component's CI
(fast, per-PR); (b) **built-wheel lane** — the component's wheel is
built, installed into a clean venv, and the kit runs against the
installed entry points (catches packaging gaps: missing data files,
console-script drift — the `lock.py parents[2]` class). The wheel lane
is required for release tags, optional per-PR.

**Accept:** kit lives in agent-suite as one versioned package; runs green
in agent-suite's own CI against `agent-suite` CLI verbs (dogfood first)
in both lanes; consumption instructions documented; per-component
conformance status recorded in **`data/cli-conformance.json`** (component,
kit version, contract version, lane, result, revision) — a separate
artifact; the frozen v1 feature matrix is **not** mutated to track this
horizontal effort.

### WI-3 — Component remediation (umbrella over per-repo WIs)

Named defects, owners, and dependencies — filed now, not discovered
later. P0 rows block WI-4 for their component.

| Pri | Component | Defect / work | Tracker | Depends on |
|-----|-----------|---------------|---------|------------|
| P0 | regista | structlog → stderr (kills the strip-non-JSON class at the root) | regista WI-211 (file) | WI-1 |
| P0 | regista | error envelope on `--json` error paths | regista WI-212 (file) | WI-1.5 |
| P0 | agent-notes | WI-026: `Error:` + exit 0 — audit **every** error path, not just wi_kind validation | agent-notes WI-026 | WI-1 |
| P0 | agent-notes | error envelope on `--json` error paths | agent-notes (file) | WI-1.5 |
| P0 | agent-suite | envelope + kit adoption (dogfood) | this plan | WI-1.5, WI-2 |
| P1 | regista | WI-210: bundle export output honesty (`.tar.gz` name, JSON content) | regista WI-210 | WI-1 §4 |
| P1 | all | manifest (`contract --json` + committed JSON) | per-repo (file) | WI-1 §6 |
| P1 | agent-notes | remove WI-019 consumer-side stripping | agent-notes WI-019 | regista WI-211 |
| P2 | regista | verb grammar audit (aliases for new-convention names) | per-repo (file) | WI-1 §3 |
| P2 | cairn / acb / agent-wake / dossier | contract audit + kit adoption; file per-repo WIs for violations found | per-repo (file) | WI-2 |

**Accept:** every component runs the conformance kit green in its CI;
the named P0/P1 defects closed; `data/cli-conformance.json` shows every
component at kit ≥ v1 / contract v1.

### WI-4 — Skills stop working around the tools (version-gated)

After WI-3 lands per component: sweep the skills layer (file-breadcrumb,
find-breadcrumb, update-breadcrumb, start/end/reflect, cred-* shims) and
delete every defensive workaround — JSON-line stripping, `tail -1`
harvesting, exit-code distrust, retry-on-grammar-guess. Skills then
document exact invocations against the contract.

**Gate:** workaround removal is **version-gated** — a compatibility
workaround is deleted only when SUITE.lock requires component versions
that implement CLI contract v1, and the cleanup ships in a transition
release where the workaround's absence is observable before the old
component versions leave the support window. Removing defenses while
any locked component still misbehaves reintroduces the silent-failure
class this plan exists to kill.

**Accept (behavioral, not grep):** a skill-invocation smoke suite in
agent-suite CI runs each skill-documented invocation against the locked
component versions (mutating verbs via `--dry-run`/fixture stores) and
asserts clean parses and honest exits — grammar drift or reintroduced
stripping fails the suite. A grep for stream-stripping /
exit-code-distrust patterns remains as a supplemental check only.

## 4. Sequencing and non-goals

P0 first — WI-1 §1–2 + WI-1.5 (cheap, unblocks everything), WI-2 runner
against agent-suite's own CLI (dogfood), then regista stream discipline +
envelope, then agent-notes exit codes + envelope. P1 next (manifest,
wheel lane, WI-210). P2 last, per component as its P0/P1 rows land, with
WI-4 gated on the SUITE.lock contract-version requirement.

Non-goals: no MCP migration (wake keeps its MCP server — session-push is
the one thing a CLI cannot do); no sidecar expansion; no new verbs. This
plan changes how existing surfaces behave, not what they do.
