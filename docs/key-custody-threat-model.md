# Key-custody threat model for the multi-user suite

**Status:** Approved design decision 2026-07-02
**Scope:** the per-actor Ed25519 signing path (regista Plan 026) as deployed
in a multi-user setting (blueprint §2.6). This document makes the
trusted-signing-proxy design an **explicit, documented decision** rather
than an emergent property of the UX.

---

## 1. The system under analysis

### 1.1 What signs what

| Actor | What signs | How the private key is held |
|-------|-----------|-----------------------------|
| **Human** (via dossier web UI) | work-item mutations, reviews, acceptances | Private Ed25519 key in the secret backend (Vault/AKV/DPAPI). dossier retrieves it to sign on the authenticated human's behalf. |
| **Agent** (via agent-notes CLI / cairn hooks) | breadcrumb/memory writes, tool-call attestations | Agent's own Ed25519 key, resolved from the secret backend by the CLI process at write time. |
| **System** (regista maintenance, migration) | synthetic/migration events | A system principal key, held by the operator. |

### 1.2 The signing flow (human path)

```
Human (browser)
  → LDAP auth
  → dossier (FastAPI, authenticated session)
    → regista.secrets.resolve("vault:secret/agent-suite/principals/<id>#key")
      → private key material in process memory
    → regista.append_event(..., actor_id=<human>, scheme="ed25519", key=<human's key>)
    → private key cleared from memory after signing
  → regista stores signed event
```

### 1.3 Trust boundaries

```
┌─────────────────────────────────────────────────────────────┐
│  Internet / work network                                     │
│    ┌──────────────┐         ┌──────────────────────────┐     │
│    │  Human       │──TLS───►│  dossier (web server)    │     │
│    │  (browser)   │         │  ┌────────────────────┐  │     │
│    └──────────────┘         │  │ LDAP auth          │  │     │
│                             │  │ Signing proxy      │  │     │
│                             │  │ (holds priv keys    │  │     │
│                             │  │  transiently)      │  │     │
│                             │  └────────┬───────────┘  │     │
│                             └───────────┼──────────────┘     │
│                                         │                    │
│                             ┌───────────▼──────────────┐     │
│                             │  Secret backend           │     │
│                             │  (Vault / AKV / DPAPI)    │     │
│                             │  holds ALL private keys   │     │
│                             └───────────┬──────────────┘     │
│                                         │                    │
│                             ┌───────────▼──────────────┐     │
│                             │  Postgres (regista)       │     │
│                             │  event log + key registry  │     │
│                             └──────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

**Boundary 1: network → dossier.** TLS terminates at dossier; LDAP
auth gates access. An attacker who defeats LDAP auth gains a session
but does not directly hold keys.

**Boundary 2: dossier → secret backend.** dossier authenticates to
the secret backend (AppRole / Managed Identity / Windows service
account) and can request any principal's private key. This is the
**trusted-signing-proxy** boundary — the core of this threat model.

**Boundary 3: dossier → Postgres.** dossier connects as the
per-project service role (`regista_<project>`), which can write to
the project schema. The signing key is not a DB credential; it is
an Ed25519 key used by the regista library in-process.

---

## 2. Threats and mitigations

### T1: Compromised dossier process forges any user's signature

**Description:** An attacker who achieves code execution inside the
dossier process (RCE via a dependency, template injection, auth bypass
to a signing endpoint) can call `regista.secrets.resolve` for any
principal's key and sign events as that user. This is the **primary
risk** of the trusted-signing-proxy model.

**Impact:** Forge any human's work-item mutations, reviews, or
acceptances. The audit chain would show validly-signed events
attributed to the victim — indistinguishable from legitimate activity
without out-of-band correlation.

**Mitigations (defense in depth, in priority order):**

1. **Transient key custody.** dossier retrieves the private key,
   signs the single event, and **immediately clears the key material**
   from memory (zero the buffer; do not retain in a cache or session
   variable). The key lives in process memory for milliseconds, not
   the session lifetime. This limits the window for extraction but
   does not eliminate it — a compromised process can simply re-fetch.

2. **Secret-backend access logging.** Every `secrets.resolve` call
   is logged by the backend (Vault audit log, AKV diagnostic log).
   An alert on "principal key accessed outside an authenticated
   session's write path" is the primary detection control. The log
   records *which* key was accessed and *when* — correlating this
   against the event log's signed events is the audit story: every
   key access should correspond to a signed event from that principal
   in the same time window.

3. **Per-principal secret-backend policies (Vault).** In a Vault
   deployment, each human's key can live at a distinct path
   (`secret/agent-suite/principals/<principal_id>`) with a policy
   that grants dossier's AppRole read access. In a stricter posture,
   the policy could be scoped so dossier can only read keys for
   principals with an active authenticated session — though this
   requires per-session Vault policies and is a v2 hardening, not v1.

4. **Dossier attack-surface minimization.** dossier is a server-
   rendered Jinja app (no SPA, no client-side JS framework, no
   file-upload endpoints in v1). The signing path is the only
   endpoint that touches private keys. Keep it that way — any new
   dossier feature that expands the request-handling surface expands
   the RCE attack surface for key theft.

**Residual risk:** A determined attacker with RCE in dossier can
forge signatures within the key-fetch window. This is inherent to the
trusted-signing-proxy model. The mitigations make it **detectable**
(via backend access-log correlation) and **harder** (minimal attack
surface, transient custody), but not impossible. This is an accepted
risk, documented here.

### T2: Key extraction from the secret backend

**Description:** An attacker who compromises the secret backend's
authentication (Vault token, AKV service principal, Windows service
account) can extract private keys directly, bypassing dossier
entirely.

**Impact:** Same as T1 but without dossier as an intermediary.
Potentially broader — all principals' keys, not just those with
active sessions.

**Mitigations:**

1. **Backend hardening is the perimeter.** Vault AppRole with
   secret_id rotation, AKV with Managed Identity (no secret in
   config), Windows DPAPI with machine scope. These are the
   backend's own security model — the suite inherits, does not
   replace, them.
2. **Key rotation (Plan 026 WI-3.1).** Regular rotation limits the
   value of an extracted key. The key-operations runbook (agent-suite
   Plan 001 WI-5.2) sets the cadence.
3. **Break-glass escrow (Plan 026 WI-3.3).** Dual-control escrow
   means the recovery key is not the same as any single principal's
   operational key — extracting one does not yield the other.

**Residual risk:** A compromised backend identity yields keys. This
is the backend's problem to solve; the suite's job is to make key
access **auditable** (backend logs) and **rotatable** (Plan 026).

### T3: Auth bypass — unauthenticated signing

**Description:** An attacker sends a crafted request to dossier's
signing endpoint without a valid LDAP session, tricking it into
signing as a victim.

**Mitigations:**

1. **Signing is not a separate endpoint.** The signing path is
   embedded in the work-item mutation handlers, which require an
   authenticated session. There is no standalone "sign this" API.
2. **The actor_id is derived from the session, not the request
   body.** dossier resolves `principal_id` from the authenticated
   LDAP user, not from a form field. An attacker cannot set
   `actor_id` to a victim by crafting the request.
3. **The actor↔signer equality check (Plan 026 WI-1.2) is a
   backstop.** Even if an attacker somehow injects a different
   `actor_id`, the signature verification will fail because the key
   doesn't match.

### T4: Agent-side key theft

**Description:** An agent process (running agent-notes CLI or cairn
hooks) holds its own Ed25519 key. If the agent's environment is
compromised, the key can be extracted.

**Mitigations:**

1. **Agent keys are lower-privilege than human keys.** An agent
   signs on behalf of a human (`on_behalf_of`), and the delegation
   chain is recorded. Agent-signed events are attributable to the
   agent principal, not the human — a stolen agent key forges the
   agent, not the human.
2. **Agent keys rotate independently.** An agent principal's key
   rotation doesn't require human action.
3. **The agent's key is scoped to its project.** A stolen key for
   project A's agent cannot sign events in project B (different
   service role, different schema, different key).

**Residual risk:** A stolen agent key can forge that agent's actions
within its project. Detectable via signing anomalies (unusual volume,
unusual event types) but not preventable at the crypto layer.

### T5: Key rotation gap — revoked key still trusted

**Description:** A key is revoked (Plan 026 WI-3.1) but a verifier
uses a stale public-key registry snapshot, trusting events signed
after the revocation.

**Mitigations:**

1. **The registry is the source of truth.** `regista verify` reads
   the registry at verify time, not a cached copy. A revoked key
   produces an `unregistered-signer` failure for post-revocation
   events.
2. **`valid_from` / `valid_to` windows.** A revoked key is windowed
   out — events it signed *before* the compromise marker stay valid;
   events *after* are flagged. This is Plan 026 WI-3.1's design.

---

## 3. The explicit decision

**The suite uses a trusted-signing-proxy model for human-signed
events.** dossier, the authenticated web face, retrieves the acting
human's private key from the secret backend, signs the event in-process,
and clears the key. This is a deliberate trade-off:

| Property | Trusted-signing-proxy (chosen) | Per-process key (alternative) |
|----------|-------------------------------|-------------------------------|
| Human UX | Transparent — human authenticates, signs happen | Human must manage a key agent / token per session |
| Deployment complexity | One backend, one web app | Per-session key derivation or a local agent on every human's machine |
| Compromise blast radius | All principals whose keys dossier can access | One principal (the one whose local agent is compromised) |
| Regulated-shop fit | Matches existing patterns (HSM-backed signing services, KMS proxies) | Requires per-user infrastructure not typical in a Windows/AD estate |
| Auditor familiarity | High — "the application signs on behalf of the authenticated user" is a known pattern | Low — "each user runs a local key agent" is unusual in enterprise |

**The decision is v1.** The mitigations (transient custody, backend
access logging, minimal attack surface, actor↔signer equality
enforcement) make it defensible. The architecture is **forward-
compatible** with a per-process-key or HSM-backed upgrade: the
`regista.secrets.resolve` indirection (Plan 025 WI-1.2) is the seam
where a future PKCS#11 or per-session-derivation provider drops in,
with no change to the signing path or the event format.

---

## 4. What this document does and does not claim

**Does claim:**
- The trusted-signing-proxy model is a conscious choice, not an
  accident.
- The mitigations make compromise **detectable** and **harder**, not
  impossible.
- The architecture is upgradeable to stronger custody without an
  envelope or protocol break.

**Does not claim:**
- That dossier is unexploitable. It is a web application; web
  applications have bugs.
- That the secret backend is unbreakable. That is the backend's
  security model, inherited not replaced.
- That per-actor signing prevents content forgery. It proves *who
  signed*, not that what they signed is *true*. A compromised
  signing proxy signs real-looking lies.

---

## 5. References

- Blueprint §2.6 — the multi-user model this document analyzes
- regista Plan 025 WI-1.2 — the secret-backend resolver
- regista Plan 026 WI-2.1 — per-principal private-key loading
- regista Plan 026 WI-3.3 — enrollment, escrow, break-glass
- dossier Plan 015 — the key-management UX that enacts this model
- agent-suite Plan 001 WI-5.2 — the key-operations runbook (policy)
