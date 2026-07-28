# Publication review

**Date:** 2026-07-04  
**Reviewer:** Claude (GLM 5.2)  
**Verdict:** REVOKED — re-review required before publication.

**2026-07-19 update:** The prior CLEARED verdict is revoked. A 5.18 MB
production operating-history export (`golden/operating-history/regista-
history-bundle-20260719.json`) was committed containing 1,508 complete
operational events with real identifiers and content. The export was
identified as coming from the production store in the committed README. A
denylist scan returning zero hits is not equivalent to privacy review — the
committed-identifier rule (AGENTS.md §"No work-domain identifiers") and this
review's own deployment-topology standard are violated. The export has been
removed from the tracked tree and replaced with a metadata manifest; a full
re-review is required before the repository can be cleared for publication.

**2026-07-27 note:** the identifier-gate correction below (restoring the
`hraedon` org identity that was over-redacted) is scoped to that over-redaction
only. It does **not** lift the REVOKED verdict above, which stems from the
separate operating-history-export incident and still requires a full re-review.

## What was checked

### Identifier gate

`scripts/identifier-gate.py` was run against the full tree. The following
identifiers were scrubbed and the gate is now **blocking** in CI:

| Identifier | Type | Action |
|------------|------|--------|
| `the project owner` | real name | Replaced with placeholder (personal-name PII; scrub remains — separate from the org identity below) |
| `mvmpostgres01` | internal hostname | Replaced with `suite-db.example` |
| `regista_app` | internal DB service account | Replaced with `DB-SERVICE-ACCOUNT` placeholder (via F-4 scrub; was `regista_service`, itself a real identifier) |
| `agent_notes_app` | internal DB service account | Added to gate (not present in tree) |
| `itadmin` | OS username | Added to gate (not present in tree) |

**Correction (2026-07-27):** an earlier revision of this review scrubbed the
`hraedon` GitHub org, `hraedon.com`, and `plm@hraedon.com` and recorded `hraedon/`
as a forbidden "internal org." That was over-redaction. The canonical suite
denylist (`~/.config/agent-suite/forbidden-identifiers`) deliberately excludes
`hraedon`, `hraedon.com`, and `plm@hraedon.com` — they are the **published author
identity**, not work-domain (work-domain) identifiers, and the publication-prep
criterion forbids only the work-domain set. Forbidding `hraedon` false-positives
on the real author and contradicts the rest of the codebase, which already uses
`hraedon/<repo>` throughout (`src/agent_suite/components.py`,
`src/agent_suite/release_manifest.py`, `SUITE.lock`, `tests/test_inventory.py`).
The `hraedon/<repo>` links have therefore been **restored** in `README.md`,
`pyproject.toml` (`Repository`), and `LICENSE`, and `hraedon` is **not** in the
gate. The `the project owner` personal-name scrub above is a distinct PII decision and
remains.

### Architecture boundary

`tests/test_architecture.py` asserts that every core module (`cli`,
`components`, `doctor`, `lock`, `bootstrap`, `verify_restore`) imports only the
standard library and its own modules — never a backend SDK or a component's
code. This is the mechanical enforcement of AGENTS.md's "thin orchestration"
rule. **Passes.**

### Tests

- `ruff check src tests scripts` — clean
- `mypy --strict src` — 7 files, no issues
- `pytest` (venv, stubbed) — 115 passed
- `pytest` (system, live Postgres via Docker) — interop + tamper tests pass

### Secrets

No secrets, keys, or passwords are committed. The `suite.env.example` file
contains placeholders only (`suite-db.example`, `DB-SERVICE-ACCOUNT`). The
`.gitignore` excludes `suite.env`, `*.env`, `secrets/`, `*.db`, and
`SUITE.local.lock`.

### Deployment topology

The docs reference deployment topology (Postgres hosts, secret backends,
service accounts) using **placeholders only** (`suite-db.example`,
`vault.example:8200`, `WORK-DOMAIN.vault.azure.net`, `DB-SERVICE-ACCOUNT`). No
real hostnames, domains, or principal IDs appear in any committed file.
