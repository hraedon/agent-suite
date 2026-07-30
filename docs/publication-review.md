# Publication review

**Date:** 2026-07-29
**Reviewers:** OpenCode (primary), Kimi (independent adjudication)
**Verdict:** CLEARED — ready for an owner-authorized public visibility flip.

## Incident remediation

On 2026-07-19, the prior clearance was revoked after a 5.18 MB production
operating-history export was found in Git history. It contained 1,508 complete
operational events with real identifiers and content. The tracked file was
removed immediately.

On 2026-07-29, every writable remote and local branch was rewritten with
`git-filter-repo --sensitive-data-removal`, all local reflogs were expired, and
unreachable objects were pruned. The private GitHub repository was then deleted
and recreated from a bare repository containing only the seven sanitized branch
heads. This removed the former pull-request refs and cached objects without
requiring GitHub Support.

Independent re-review then found a separately designated personal name in old
documentation history. Every local branch and stash was rewritten again with
both `--replace-text` and `--replace-message`; all linked worktrees were clean
before realignment, and local reflogs and unreachable objects were pruned. The
GitHub repository was deleted and recreated a second time from the seven final
sanitized heads. Pre-rewrite commit ids from both incidents now return not found.

Recreation evidence:

- The old sensitive commit and blob return not found through the GitHub API.
- `git ls-remote` reports seven branch heads, no tags, and no `refs/pull/*` refs.
- The recreated repository has zero issues, pull requests, releases, forks,
  stars, and watchers.
- `git log --all -- golden/operating-history/regista-history-bundle-20260719.json`
  and `git rev-list --objects --all -- <same-path>` return no results.
- The repository remains private during this re-review.

## What was checked

### Identifier gate

`scripts/check_committed_identifiers.py` was run against the full tracked tree
with the canonical denylist from
`~/.config/agent-suite/forbidden-identifiers`. A separate history scan checked
both content changes and commit messages for every canonical entry. Both scans
passed.

The canonical policy forbids the work-domain set only. The `hraedon` published
author identity and lab identifiers are intentionally allowed. A personal name
identified during the earlier review was governed by a separate PII decision
and has been removed from both the current tree and history.

CI injects `AGENT_SUITE_FORBIDDEN_IDENTIFIERS` from the repository secret and
now fails closed if that secret is empty before invoking the canonical gate.

### Architecture boundary

`tests/test_architecture.py` mechanically enforces the stdlib-first thin-core
boundary. It passes.

### Tests

- `ruff check src tests scripts` — clean.
- `mypy --strict src scripts/check_committed_identifiers.py` — clean in 42 files.
- `pytest -q` — 1,103 passed, 18 skipped.
- Recreated-remote CI run
  [30490402495](https://github.com/hraedon/agent-suite/actions/runs/30490402495)
  passed every Linux, Windows, feature-probe, lock-agreement, and interop job.
  (An earlier draft cited run `30490199384`, which validated the preceding commit
  `6bb6f79`; `30490402495` is the run for the then-current tip `8fc1f1b`. Both
  passed — the correction is to the citation, not the verdict.)

### Secrets

No secrets, keys, or passwords are committed. `detect-secrets` scanned every
tracked file; each unverified candidate was manually reviewed as a synthetic
test credential, placeholder DSN, keyword reference, or immutable Git SHA.
`pip-audit` reported no known vulnerabilities. The canonical identifier scan
also passed.

### Deployment topology

Deployment documentation uses placeholders for work-domain topology and service
accounts. Lab topology and the published author identity are allowed by the
canonical publication policy.


---

## Addendum, 2026-07-30 — multi-word identifier audit

The 2026-07-29 verdict above is **superseded on one point of fact**: its history
scan reported clean, but that scan was *structurally incapable* of finding the
class of identifier described here. The verdict's other findings stand.

### What was wrong with the gate

`parse_identifier_set` split the denylist on whitespace unconditionally. A
multi-word identifier therefore could not be *expressed*: its halves became
short tokens that the minimum-length filter discarded, leaving an entry that
matched nothing. Separately, **no gate anywhere scanned commit messages** — not
the pre-commit hook, not CI.

Consequence: a real two-word work-domain identifier reached the tracked tree of
14 repositories and the history of 16, **eight of them public**. The vector was
the canonical gate scaffold itself (`githooks/pre-commit`), whose explanatory
comment named the work domain as an illustrative example; `project-initiation`
copied it into every new repo. Separately, `gpo-lens` — public — carried a bare
form of the same name and an internal `.local` AD domain in three commit
messages, two of which were the very commits that redacted those identifiers
from files.

### What was fixed

- Denylist entries may be double-quoted and match any separator run — spaced,
  hyphenated, underscored, dotted, or wrapped across a line break. The leak
  occurred in three of those spellings, which is why single-spelling matching
  was not enough.
- `githooks/commit-msg` and `githooks/pre-push` scan commit messages; a
  `message-gate` CI job does the same with `fetch-depth: 0`. Mechanically
  asserted by `tests/test_identifier_gate.py::test_ci_scans_commit_messages`.
- WI-019: `scripts/check_publication_plumbing.py` + `publication.toml` verify
  push destination, author identity, and declared visibility before a
  publication-sensitive push. Layer 3/4 accident prevention, not a security
  boundary.
- WI-027: the four residual fails-open branches are closed (unreadable tracked
  file now fails the gate instead of being skipped; git failures exit 1 cleanly
  rather than tracebacking; symlink targets are scanned, not followed; the
  no-op branch messages are asserted).
- The canonical template, `sync-identifier-gate.sh`, and the three skills that
  seeded the leak were corrected, and the hardened gate was rolled to every
  repository in the estate. Four divergent gate vintages were reconciled.

### Independent secrets sweep

`gitleaks` 8.30.1 over the full history of all 24 repositories, then again over
mirror clones of the 14 public ones so `refs/pull/*` commits were included:
**65 findings, all benign**, all from the `generic-api-key` rule. 57 sit in
test/fixture paths; the 8 in non-test paths were each read and resolved
(a base64 string decoding to `fake-mac-key-...`, a published Microsoft AD schema
GUID, two `REPLACE-ME-32-BYTES-HEX` placeholders, three plan-document examples,
one synthetic Kerberos cache UUID). Zero findings were unique to `refs/pull/*`.

regista's committed ed25519 test keys were checked against the operator's live
key material (`~/.config/regista/keys.json` and `principals/`) by SHA-256
fingerprint of every 40+ character token, without printing values: **zero
overlap**. The committed keys are test-only.

Note that gitleaks did **not** flag the identifier leak — it is not a secret
pattern. A denylist gate and a secrets scanner cover different ground and
neither subsumes the other. Both are now required.

### Residual exposure — accepted, by channel

The identifier is a work-domain *name*; nothing access-bearing was disclosed
(no credential, key, token, IP, reachable hostname, or account name). The
`.local` domain is RFC 6762-reserved and non-routable.

| Channel | State |
|---|---|
| Default-branch trees (what GitHub code search indexes) | **clean estate-wide** |
| Branches and tags on every remote | **clean** (force-pushed, all refs) |
| `refs/pull/*` | **residual** — server-side, not rewritable by a client; only delete-and-recreate purges it |
| Unreachable objects by SHA | **residual** — a force-push does not purge GitHub's retained objects; old commits stay fetchable by SHA |
| PyPI `dossier_hraedon-0.0.1.tar.gz` (2026-07-20) | **permanent** — ships `githooks/pre-commit`; sdists are immutable and mirrored. No git operation can affect this |
| Third-party clones taken 2026-07-05 → 2026-07-30 | unknowable; clone traffic in that window was overwhelmingly CI |

Exposure window ≈ 25 days. Human attention was low: GitHub traffic showed a peak
of 10 unique *viewers* (gpo-studio), most repos 0–2; the large clone counts are
this estate's own CI. No stars, forks, or watchers on any affected repository.

**Accepted** by the owner on the ground that the identifier is a domain name of
low sensitivity, on projects built primarily for that work context, and that a
complete purge is unachievable anyway once an immutable PyPI artifact exists.
The controls, not the purge, are the remediation.

### Known gaps

- `sysadmin_competence_evaluation` is **public with no identifier gate at all**
  and no CI denylist secret configured.
- `patina` has no gate and no remote.
- `ad-steward`'s default branch is `eam-tier-rules-impl`, not `main`; both were
  remediated, but a default branch that is not `main` is easy to overlook when
  reasoning about the indexed surface.
