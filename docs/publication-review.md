# Publication review

**Date:** 2026-07-29
**Reviewers:** OpenCode (primary), Kimi (independent adjudication)
**Verdict:** PENDING — final recreated-remote CI required.

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
- Recreated-remote CI will be required green before final clearance.

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
