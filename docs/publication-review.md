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
| PyPI `dossier_hraedon-0.0.1.tar.gz` (2026-07-20) | **permanent, and narrow** — see the measured scope below |
| Third-party clones taken 2026-07-05 → 2026-07-30 | unknowable; clone traffic in that window was overwhelmingly CI |

Exposure window ≈ 25 days. Human attention was low: GitHub traffic showed a peak
of 10 unique *viewers* (gpo-studio), most repos 0–2; the large clone counts are
this estate's own CI. No stars, forks, or watchers on any affected repository.

**Accepted** by the owner on the ground that the identifier is a domain name of
low sensitivity, on projects built primarily for that work context, and that a
complete purge is unachievable anyway once an immutable PyPI artifact exists.
The controls, not the purge, are the remediation.

### PyPI exposure, measured

Every file of every version of all four published packages was downloaded and
scanned (14 artifacts). **Exactly one contains the identifier:**

- `dossier_hraedon-0.0.1.tar.gz` — 364,754 bytes, uploaded
  2026-07-20T06:47:58Z, not yanked. Of its **180 members, one file**:
  `githooks/pre-commit`, **3 occurrences, all comment lines** (5, 15, 17), and
  only the two-word org name. The bare form and the internal `.local` domain
  never reached PyPI at all.
- The matching **wheel is clean** (wheels package only `src/dossier`).
- **`PKG-INFO` and `README` are clean**, so the identifier never appeared in
  PyPI's rendered metadata — not on the project page, not in PyPI search, not
  indexed by search engines. Discovery requires downloading and unpacking the
  tarball.
- All other 13 artifacts (regista-hraedon 0.5.1–0.5.4, agent-notes-hraedon
  1.0.0, agent-suite-conformance 1.0.0; sdist and wheel each) are clean.
- Package downloads: 412 with mirrors / 144 without. PyPI's public API does not
  break down by file type, so the tarball's own fetch count is unknown; a normal
  `pip install` resolves the universally-compatible wheel and never touches it.

**Fixed forward, not retracted:** dossier now declares
`[tool.hatch.build.targets.sdist]` excludes (`githooks`, `.github`, `plans`,
`reflections`, `samples`), so no future release can carry dev tooling — 163
members instead of 180, verified by building it. `0.0.1` is deliberately **not**
yanked: yanking stops resolution but leaves the file downloadable, so it is
signal rather than protection.

### gpo-lens: deleted and recreated, 2026-07-30

gpo-lens held the most sensitive item found — an internal `.local` AD domain
paired with an explicit `(work)` label — in three commit messages, two of which
were the commits that redacted those identifiers from files. A history rewrite
plus force-push cleaned its branches and tags, but the three commits survived in
`refs/pull/*`, which no client can rewrite.

It was therefore deleted and recreated from the rewritten history: cheapest
purge in the estate (2 PR discussions, 1 release) against the highest-sensitivity
content. Restored: `main` + 11 tags, the `GPO_LENS_FORBIDDEN_IDENTIFIERS` secret,
the v1.2.0 release with its original notes, description, and public visibility.

Verification: the three pre-rewrite commit ids return HTTP 422 "No commit found";
a mirror clone shows `refs/heads/*` 1 and `refs/tags/*` 11 with **no
`refs/pull/*`**; scanning 1,366 blobs and every commit message across all refs
yields zero violations. Backups retained in the session scratchpad (full
pre-deletion mirror including the PR refs, plus a bundle of the rewritten
history).

### No over-redaction

The inverse failure was checked, because it has happened here before (an earlier
gate carried the published author identity in its denylist; a later pass
clobbered real lab links, restored in `905f0bb`). Against pre-rewrite state, the
two all-entries rewrites touched **only** work-domain identifiers: one reflection
file in acme-adcs-ra, three commit messages in gpo-lens. Lab references survive
intact everywhere (gpo-studio 94 files referencing the lab identity, cert-watch
40, and so on). The canonical denylist contains no lab-shaped entry, now pinned
by `test_canonical_denylist_forbids_only_work_domain_identifiers`.

### Precondition DISCHARGED, and the flip — 2026-07-30

The blocking precondition recorded here (this repository's own history still
contained the identifier, because its tree was fixed forward rather than
rewritten) has been cleared, in the order the record demanded:

1. History rewritten with `git-filter-repo --replace-text --replace-message`
   across **all seven branches**, in a **bare clone** — bare clones fetch
   `refs/heads/*` and tags but not `refs/pull/*`, and filter-repo prompts on
   sanity checks in a working repo and dies under no TTY.
2. Verified before touching the remote: 888 blobs scanned with the hardened
   multi-word gate, **0 violating**; **0 violating commit messages** across
   `--all`; tracked tree clean.
3. Repository **deleted and recreated** to drop its six `refs/pull/*`, which no
   client can rewrite. All seven branches restored, default branch set to `main`,
   the `AGENT_SUITE_FORBIDDEN_IDENTIFIERS` secret restored, description restored.
   No tags or releases existed to restore.
4. Verified after: pre-rewrite commit ids (`905f0bbe5`, `7df3ca089`, `ccc0b4109`)
   return "No commit found"; a mirror clone shows `refs/heads/*` 7 and **no
   `refs/pull/*`**; full blob and message scan of the recreated remote clean.
5. Visibility flipped to **public**, owner-authorized.

Recovery path retained: a full pre-deletion mirror (including the PR refs) plus
the rewritten bare clone, in the session scratchpad.

Residual, unchanged from the accepted set: GitHub retains unreachable objects by
SHA on repositories that were force-pushed rather than recreated, and the
immutable PyPI sdist. Neither applies to this repository, which was recreated.

**Local note:** fourteen local-only branches in the operator's checkout still sit
on the pre-rewrite history line and therefore still contain the identifier. They
are local disk only, never pushed, and the `pre-push` message gate now blocks any
attempt to publish them. They need triage (rebase onto the new history or delete)
by whoever owns that unmerged work.

### Known gaps

- `ad-steward`'s default branch is `eam-tier-rules-impl`, not `main`; both were
  remediated, but a default branch that is not `main` is easy to overlook when
  reasoning about the indexed surface.
- `refs/pull/*` residual remains on `dossier`, `vitrine`,
  `agent-capability-broker`, `gpo-studio`, `cert-watch`, `usage-dashboard`,
  `acme-adcs-ra` and `ad-steward` — the two-word org name only, accepted.
- Retained unreachable objects remain fetchable by SHA on every force-pushed
  repository — the two-word org name only, accepted.

### Closed since

- `sysadmin_competence_evaluation` was public with **no gate at all** and no CI
  secret; both are now configured.
- `patina` had no gate; it now has one (still no remote, so declared
  private-until-review).
