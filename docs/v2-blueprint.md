# Agent Suite v2 — gaps review and plan index

**Drafted:** 2026-07-07 by Claude (Fable 5), from a cross-repo survey + live
verification pass (doctor runs, store queries, harness-binary inspection) on
the operator's machine.
**Relationship to v1:** `/projects/agent-suite-blueprint.md` was the strategy
that made six tools deploy as one suite; its per-component cohesion plans are
now landed or in tail. This document is the v2 layer: what the review found
still missing between "the mechanisms exist" and "a team lives on this," and
the plan series that closes it.

---

## 1. Headline findings (verified, not asserted)

1. **Provenance is not capturing harness output.** The compliance keystone is
   inert: cairn is unwired on the only real deployment (doctor: no config, all
   five hooks missing), the live store's only tool-call attestations are
   synthetic dogfood events (last activity 2026-07-04, fabricated harness
   version), and — decisive — the Claude hook parses `tool_output` while the
   installed harness (2.1.200) emits `tool_response` (zero occurrences of
   `tool_output` in the binary). Wired as-is it would attest empty digests.
   The unit tests hand-feed the same wrong field, so CI is structurally blind
   to it. Digest semantics are also unverifiable for outputs beyond the 2000-
   char transport truncation. → **agent-provenance Plan 009.**
2. **The suite has never been deployed as a suite.** On the home box —
   deployment #1 — `agent-suite doctor` reports 5/6 components failed and no
   SUITE.lock, while the components run fine on bespoke legacy env vars. The
   bootstrap, lock, and config contract are exercised only in CI. Failure
   detail is illegible (`doctor exit 1: no stderr`). → **agent-suite Plan 004.**
3. **Humans can see work items, not agent work.** dossier renders issues,
   history, search, keys — but sessions, tool-call trails, files-touched, and
   chain-verification status have no surface; agent knowledge (breadcrumbs,
   memories, reflections) is agent-face-only; nothing notifies a human that a
   strict-gate item awaits their accept. The mixed human+agent record the
   convergence proved at the store level is still invisible at eye level.
   → **dossier Plans 017/018, agent-notes Plan 018, agent-wake Plan 005.**
4. **Contract drift persists at the edges.** acb's `doctor --json` lacks the
   top-level `ok`, so the umbrella misclassifies a healthy acb as failed; its
   e2e half remains asserted-not-proven. → **acb Plan 006.**
5. **Nothing is operated.** No upgrade procedure for SUITE.lock, no scheduled
   backup/verify-restore, no alerting when doctor goes red, no key-age or
   store-growth watch. → **agent-suite Plan 005.**

## 2. The v2 plan series

| Plan | Repo | One line |
|------|------|----------|
| **agent-provenance 009** | capture correctness + live proof | Fix hook parsing against recorded-real payloads, verifiable digest semantics, wire + live E2E proof, subagent/compaction/transcript coverage, silence-is-a-finding. |
| **agent-suite 004** | dogfood deployment | suite.env + bootstrap + SUITE.lock + green doctor on the home box, then a clean-machine run; legible failures; closes Plan 001's gated tail. |
| **dossier 017** | agent-activity window | Sessions, tool-call trails on work items, files-touched index, chain-health widget, verified-history stamps. |
| **dossier 018** | working views + notifications | Review queue, my-work, activity feed; notification seam (awaiting-your-accept, digests) delivered via wake. |
| **agent-notes 018** | knowledge legibility | Memories/reflections as signed regista entities; human browse/read via dossier (pairs with dossier Plan 009); cross-face contract test. |
| **agent-wake 005** | human-directed delivery | Principal identity layer, webhook + email adapters, doctor-red alerting loop. |
| **acb 006** | doctor conformance + e2e proof | Top-level `ok` per contract; live browser proof both harnesses; provenance composition check. |
| **agent-suite 005** | operate the suite | `agent-suite upgrade`/rollback as lock transitions; scheduled backup + verify-restore; key-age + growth watch; alerting loop. |

**Existing tails that gate v2 but need no new plan:** regista 027 (finish
strict-gate/assurance), 028 (physical archival validation, deferred WIs),
029 (backend-aware key custody, proposed); agent-notes 017 / agent-wake 004
remaining WIs; the four private repos' publication gates + owner-set CI
secrets before any public flip.

## 3. Sequencing

```
Wave 1 — Truth            agent-provenance 009 (Ph 1–2)  →  agent-suite 004
  The record must be real before anything renders or alerts on it.
  Exit: cairn live proof green + home-box doctor green + SUITE.lock committed.

Wave 2 — Human visibility dossier 017 → dossier 018 ∥ agent-notes 018 ∥ wake 005
  The regulated pitch made visible: trails, verification status, queues, nudges.
  (dossier 018 Phase 1 has no dependency and may start during Wave 1.)

Wave 3 — Operations       agent-suite 005 ∥ acb 006 ∥ provenance 009 (Ph 3–4)
  Upgrades, scheduled protection, alerting, edge-contract closure.
```

**Honest ordering advice:** Wave 1 is not optional and not parallelizable away
— finding 1 means the suite's core claim is currently false in practice, and
every Wave 2 surface would render an empty or wrong record. Do 009 Phase 1
before wiring anything. Wave 2 is where the daily-use value lands for the
work-pilot audience; Wave 3 is what the pilot's reviewers will ask about after
the demo.

## 4. What stays out of v2

- Human authoring of knowledge notes in dossier (read-first; write later).
- The full team model (dossier Plan 004) beyond person-scoped views.
- A second model/harness investment beyond keeping opencode green (v1 ruling
  stands).
- Completing regista 028 physical archival (monitor growth first — WI in
  agent-suite 005).
- Any control-plane/daemon (non-goal, permanent).
