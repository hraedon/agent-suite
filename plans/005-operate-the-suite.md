# Plan 005 — Operate the suite: upgrades, backups on a cadence, alerting

**Status:** Proposed 2026-07-07.
**Author:** Claude (Fable 5), from the 2026-07-07 suite v2 gaps review
**Strategic role:** v1 made the suite installable and verifiable at a point in
time. A real deployment lives for years: components move, the store grows, keys
rotate, things break at 2am. Today there is no upgrade path (SUITE.lock is a
pin with no procedure to advance it), no scheduled backup (verify-restore
exists but nothing runs it), and no alerting (a red doctor is only red when
someone runs it). This plan is the difference between "deployed once" and
"operated" — the questions a change-advisory board asks after the pilot demo.

## Ground truth at time of writing

- `verify-restore` and the DR runbook shipped (Plan 001 WI-4.x) but are
  on-demand only; no timer/scheduled execution exists anywhere.
- SUITE.lock (once Plan 004 WI-1.3 creates the first real one) has no
  documented bump procedure; "advance a pin" currently means hand-editing.
- `doctor` is invocation-only. The suite has wake for signaling, but nothing
  schedules a health run or routes a red result to a human (agent-wake Plan
  005 WI-1.4 owns delivery; this plan owns the scheduling and emitting).
- Key rotation mechanics exist (regista 026, dossier 015) with a policy
  runbook, but no cadence enforcement or expiry warning surfaces in doctor.
- regista Plan 028 (retention/archival) is partially landed — sealing yes,
  physical archival not validated. Log growth is real but not urgent; this
  plan schedules the *monitoring* of it, not the completion of 028.

## Principles

- **Use the OS scheduler, not a daemon.** systemd timers / Windows Scheduled
  Tasks, consistent with the no-control-plane non-goal.
- **An upgrade is a lock transition, and it's evidence.** Old lock → new lock,
  gated by the interop CI, recorded like any other auditable change.
- **Alerts route through the suite's own signaling.** Health emission here,
  delivery via agent-wake Plan 005 — no parallel notification stack.

---

## Phase 1 — Upgrade and rollback

### WI-1.1 — `agent-suite upgrade`
- A command that advances SUITE.lock: fetch components' targets, run the
  suite-interop proof against the candidate set (locally or via CI), and on
  green rewrite the lock + apply per component (pip/pipx upgrade, image pull,
  service restart via its unit). `--component` to advance one pin; `--check`
  to report available advances without acting.
- **AC:** advancing one component on the home box is a single command whose
  failure (red interop) leaves the deployed set and lock untouched; the lock
  diff is committed with the interop evidence referenced.

### WI-1.2 — Rollback = previous lock
- `agent-suite upgrade --to <lock-ref>` applies a prior committed lock.
  Document what rollback *cannot* undo (schema migrations, workflow versions —
  regista's compatibility rules decide), and make the command refuse a rollback
  that would cross a migration boundary rather than half-apply it.
- **AC:** after a WI-1.1 upgrade, rolling back restores the prior set and
  doctor green; attempting a rollback across a schema migration is refused
  with a clear explanation.

## Phase 2 — Scheduled protection

### WI-2.1 — Backup + verify-restore on a timer
- Ship timer units (systemd + Windows equivalent) for: nightly `pg_dump` of
  the store with documented retention, and a periodic (weekly) automated
  verify-restore into a scratch database proving the backup is
  cryptographically intact — the Plan 001 mechanism, now actually running.
  Failures emit per WI-3.1.
- **AC:** on the home box, a scheduled run produces a dump + a green
  verify-restore without human action; deleting/corrupting a dump makes the
  next verify run emit a failure signal.

### WI-2.2 — Key and retention watch
- doctor gains age checks: signing-key age vs the key-operations policy's
  rotation cadence (warn approaching, fail past); store growth telemetry
  (events/bytes per project) so the 028 archival decision is made from data.
- **AC:** a key older than policy warns in doctor with the runbook reference;
  growth numbers appear in `doctor --json` and the deployment record.

## Phase 3 — The alerting loop

### WI-3.1 — Scheduled doctor + red-routing
- A timer runs `agent-suite doctor --json`; on red/degraded (and on
  recovery), post the result to agent-wake's ingress for human delivery
  (wake Plan 005 WI-1.4). Debounce: state-change emission, not every-run spam.
  Include the last-attestation-age finding (agent-provenance 009 WI-4.1) so a
  silently-unwired recorder pages someone.
- **AC:** forcing a component red on the home box produces one delivered
  alert within the interval and one recovery notice after the fix; a stable
  state produces nothing.

---

## Sequencing

Requires Plan 004 (there is nothing to operate until the suite is deployed).
Phase 2 first if the pilot timeline compresses — data protection beats upgrade
ergonomics. Phase 3 pairs with agent-wake Plan 005; until wake's delivery leg
exists, alerts land in a test receiver. regista 027 completion and 029 remain
the regista-side tail and are tracked there, not here.
