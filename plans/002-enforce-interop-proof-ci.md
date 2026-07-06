# Plan 002 — Enforce the face-level interop proof in CI

**Status:** Proposed 2026-07-06, from a post-1.0 cross-repo review (Claude, Opus 4.8).
**Author:** Claude (Opus 4.8)
**Strategic role:** The suite's flagship guarantee is that the **two real faces**
(agent-notes' `RegistaFace`, dossier's `RegistaGateway`) interoperate over one
regista project — Plan 001 WI-2.2, blueprint §2.2. The proof exists
(`tests/test_interop.py::test_drive_work_item_across_real_faces_to_done`) and is
real. But in CI it is currently **green-by-skip**: the face packages were installed
"best effort" from *then-private* git repos (`.github/workflows/ci.yml:84-88`), the
install failed for lack of auth, and the face-level test skipped. A skip and a pass
produce the same green badge. Now that all three repos are **public**, the install
can succeed — so this plan makes the proof actually *run* and makes a future
regression *fail* instead of silently reverting to a skip.

## Ground truth at time of writing

- `test_interop.py` has two levels: spine-level (drives regista's canonical workflow
  directly — always runs) and face-level (imports the real face packages — skips
  unless both are importable in the same interpreter).
- `ci.yml` installs regista pinned to git (`:77`), then the two faces "best effort
  until public" (`:84-88`) with failure swallowed. With the faces private, that step
  no-op'd and the face-level test hit its skip guard.
- All of regista, agent-notes, and dossier are now **public** — the blocker the
  best-effort guard was written around is gone.

## Work items

### WI-1 — Install the faces as a hard CI step
- Now that agent-notes and dossier are public, drop the best-effort/failure-swallow
  guard. Install both faces (pinned to a SHA or `@main`) as a required step; if the
  install fails, CI fails. Remove the "until public" comment.

### WI-2 — Turn the face-level skip into a required assertion
- Add an env flag (e.g. `INTEROP_REQUIRE_FACES=1`) that the CI job sets. When set,
  `test_drive_work_item_across_real_faces_to_done` **errors** instead of skipping if
  either face is not importable. Locally (flag unset) it still skips cleanly. This
  closes the "skip looks like pass" hole: face packaging can no longer silently
  regress the suite's flagship guarantee.

### WI-3 — Guarantee the Postgres path executes in CI
- Confirm the ephemeral-Postgres fixture runs on the CI runner (Docker available) or
  wire a Postgres service container and pass `INTEROP_DSN`, so the proof genuinely
  drives a database rather than skipping on "no Docker."

### WI-4 — Verify
- Confirm in a CI run that **both** interop tests execute and pass (not skip) —
  inspect the run log for the face-level test id, not just the green check.

## Notes

- This is small and high-leverage: the code under test already works (proven locally,
  convergence e2e, 2026-06-29). The gap is purely that CI wasn't *enforcing* it. The
  fix converts an existing local proof into a continuous one.
- Sequence after nothing — independent of regista Plan 029. Can be dispatched now.
