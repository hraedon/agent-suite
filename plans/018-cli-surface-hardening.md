# Plan 018 — CLI surface hardening: the CLI is an API contract

**Status:** Proposed 2026-07-19.
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

## 2. Work items

### WI-1 — The CLI contract (`docs/cli-contract.md`)

One page, normative, versioned. Contents:

1. **Stream discipline.** Under `--json`, stdout carries exactly one JSON
   document (or one NDJSON stream where documented) and nothing else; all
   logging, progress, and diagnostics go to stderr. Without `--json`,
   human output goes to stdout, diagnostics still to stderr.
2. **Exit-code taxonomy.** `0` success; `1` operational failure (and every
   path that prints an error message); `2` usage error (argparse default).
   No path may print `Error:` and exit 0. Partial success must pick a side
   and document it.
3. **Grammar conventions.** Entity identifiers as positionals; `--json` on
   every verb; verb naming (`noun verb` order, kebab-case flags); flag
   deprecation policy (alias one release, then remove — the §2.1 config
   pattern applied to flags).
4. **Output honesty.** The output format matches what the name/extension
   implies; refuse or warn on mismatch (the WI-210 class).
5. **Machine-readable errors.** Under `--json`, errors are also JSON on
   stdout (`{ok: false, error: {...}}` shape) with the nonzero exit —
   consumers get one parse path for both outcomes.

**Accept:** contract committed; each component's AGENTS.md links it; a
decision record per `docs/process-calibration.md` §1 records the
CLI-over-MCP surface decision with its falsifier (harness MCP interposition
+ lazy tool loading + single-harness standardization would reopen it).

### WI-2 — Conformance kit (vendable test suite)

A small pytest module each component copies (or imports) into its CI —
the `test_identifier_gate.py` pattern generalized: fixture-driven
behavioral tests that prove the contract, not the implementation.

Checks, parameterized over the component's verb list: `--json` stdout
parses as a single JSON document with zero non-JSON bytes; every
documented error fixture (unknown enum value, unresolvable reference,
missing required flag) exits nonzero with the documented shape; usage
errors exit 2; `--help` exits 0 on every verb.

**Accept:** kit lives in agent-suite; runs green in agent-suite's own CI
against `agent-suite` CLI verbs (dogfood first); vendoring instructions
documented; conformance status per component surfaced in the feature
matrix as probe-emitted rows, not hand-assessed ones (Gate 0 WS3
discipline).

### WI-3 — Component remediation (umbrella over per-repo WIs)

Evidence-driven sweep, each in the component's own tracker:

- **regista:** structlog → stderr (kills the whole strip-non-JSON class at
  the root); WI-210 output honesty; verb grammar audit.
- **agent-notes:** WI-026 exit codes (audit *every* error path, not just
  wi_kind validation); remove the WI-019 consumer-side stripping once
  regista emits clean streams.
- **cairn / acb / agent-wake / dossier CLI / agent-suite CLI:** contract
  audit + conformance kit adoption; file per-repo WIs for violations found.

**Accept:** every component runs the conformance kit green in its CI;
the named defects (WI-019 workaround, WI-026, WI-210) closed.

### WI-4 — Skills stop working around the tools

After WI-3 lands per component: sweep the skills layer (file-breadcrumb,
find-breadcrumb, update-breadcrumb, start/end/reflect, cred-* shims) and
delete every defensive workaround — JSON-line stripping, `tail -1`
harvesting, exit-code distrust, retry-on-grammar-guess. Skills then
document exact invocations against the contract. Stretch: a drift smoke
(script that runs each skill-documented invocation with `--help` /
`--dry-run` and fails on grammar drift) runnable in agent-suite CI.

**Accept:** grep of the skills tree finds zero stream-stripping or
exit-code-distrust patterns targeting suite CLIs; each skill's documented
invocations verified against the shipped CLIs.

## 3. Sequencing and non-goals

WI-1 first (cheap, unblocks everything); WI-2 against agent-suite's own
CLI next (dogfood); WI-3 component-by-component with regista's stream
discipline first (it unblocks the biggest workaround class); WI-4 last,
per component as WI-3 lands.

Non-goals: no MCP migration (wake keeps its MCP server — session-push is
the one thing a CLI cannot do); no sidecar expansion; no new verbs. This
plan changes how existing surfaces behave, not what they do.
