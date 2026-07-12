# Plan 013 — Full v1 human surfaces: one Windows-first suite console

**Status:** In Progress — Phase 0 contract foundations implemented 2026-07-12:
machine-readable human-surface registry, validated provider/role/risk/status
vocabulary, and deterministic non-acting Windows setup protocol. Production
Windows probes/execution and dossier consumption remain.  
**Owner:** agent-suite coordinates; dossier owns the shared web surface; each
component owns its provider contract.  
**Depends:** Plans 003, 008, and 009; dossier Plans 015 and 018–024; regista
Plan 031.  
**Strategic role:** Turn the suite from several capable components with CLIs
into a product a predominantly Windows team can install, understand, operate,
and audit without learning each component's internals.

## 1. Product decision

The v1 human product has two surfaces, not seven:

1. **Dossier is the shared suite console.** It is the normal browser surface
   for collaborators, reviewers, auditors, security administrators, and
   operators. Component state is rendered through component-owned contracts;
   dossier does not copy their truth or reimplement their actions.
2. **Agent Suite Setup is the Windows host surface.** It covers installation,
   local harness wiring, diagnostics, signed-bundle apply, and recovery before
   dossier is reachable. It is narrow host tooling, not a desktop clone of
   dossier and not a fleet control plane.

Component CLIs remain supported for agents, automation, expert diagnosis, and
break-glass recovery. Cairn's self-contained static evidence report remains an
independent offline artifact. No other component receives a separate production
web application for v1.

Windows is a required v1 platform. The supported team path is native Windows
clients and harnesses plus one centrally hosted dossier URL. The central service
may itself run as a Windows Service through WinSW. WSL is not a prerequisite.

## 2. Human roles and required jobs

### Collaborator

- see assigned work and work performed by their agents;
- create, discuss, transition, and search work;
- browse signed knowledge and follow links to work and evidence;
- understand their signing identity without handling key material;
- choose notification preferences and follow authorization-checked deep links.

### Reviewer

- work an eligible review queue across authorized projects;
- understand independence, lineage, coverage, and degradation;
- inspect agent sessions, tool calls, and files associated with the work;
- request changes, record a verdict, and accept only when the configured gate
  permits it;
- complete the workflow with keyboard and assistive technology alone.

### Auditor or investigator

- define a case-bound evidence scope;
- see exactly what is included, excluded, verified, stale, or unavailable;
- obtain a redacted export plus offline verification material;
- print or save a legible report without production credentials;
- inspect disclosure approvals and evidence handling history.

### Security or identity administrator

- enroll, rotate, revoke, and reconcile principal keys through dossier;
- bind human identities to validated Entra object identifiers;
- require step-up and independent approval for protected operations;
- see project access, signing coverage, custody posture, and offboarding state;
- never receive private-key or secret values in the browser.

### Suite operator

- understand estate/profile health, lock drift, proof freshness, backup and
  restore posture, delivery failures, key age, and capacity;
- draft and approve safe configuration changes in dossier;
- apply host/deployment changes through a signed bundle using Agent Suite Setup;
- install, diagnose, repair, upgrade, and recover on Windows without reading
  component source or requiring Linux experience.

## 3. Surface ownership contract

| Domain | Normal human surface | Owning truth/action |
|---|---|---|
| Work and review | dossier | regista workflow and events |
| Exact knowledge and search | dossier | agent-notes/regista knowledge contract |
| Sessions, tools, files, coverage | dossier | cairn/regista evidence contract |
| Offline evidence | cairn static report | cairn verifier + regista bundle |
| Identity and public-key lifecycle | dossier | regista principal-lifecycle API |
| Private-key custody | no browser surface | custody provider/local Windows helper |
| Capabilities and drift | dossier inventory/approval | ACB describe/plan/apply/receipt |
| Notifications and delivery | dossier | dossier policy + agent-wake delivery |
| Estate health and configuration | dossier | agent-suite/component providers |
| Install, local wiring, repair | Agent Suite Setup | agent-suite + component CLIs |
| Root secrets, DB restore, TLS roots | guided host operation | operator/secret backend/DB tooling |

## 4. Dossier information architecture

The supported console has six primary areas:

1. **Work** — dashboard, my work, review, projects, search.
2. **Knowledge** — notes, memories, decisions, reflections, links, search.
3. **Activity** — sessions, tools, files, principals, degradation.
4. **Evidence** — integrity, cases, exports, disclosures, verification history.
5. **Operations** — health, releases, protection, delivery, drift, capacity.
6. **Administration** — projects, access, identities, keys, policies,
   integrations, pending changes.

Identity, preferences, signing history, accessibility, and sign-out live in the
user menu. Navigation and landing content are role-aware, but authorization is
always enforced at the route/provider boundary and never inferred from hidden
navigation.

Every status surface uses the shared vocabulary `ok`, `warning`, `failed`,
`unknown`, `unsupported`, `unreachable`, and `not configured`. Color is never
the only carrier of meaning. Pages identify the source and freshness of their
data and must not present a cached or partial result as current truth.

## 5. Windows Agent Suite Setup

### Phase 1 — Supported packaging and preflight

Provide a signed, versioned Windows entry point installable from an immutable
release artifact. It may be implemented as a small packaged executable invoking
the stdlib orchestration core and rendering a local loopback UI, or as a native
installer with an equivalent accessible wizard. It must not require bash, WSL,
Docker Desktop for client-only profiles, or manually edited JSON.

Preflight reports:

- supported Windows/Python/PowerShell versions;
- service-account and elevation posture;
- Postgres/DNS/TLS reachability;
- secret-provider availability without reading secret values;
- selected profile, components, harnesses, and required privileges;
- existing installation and ownership conflicts;
- immutable release/lock identity.

### Phase 2 — Install and local onboarding

- install the exact locked artifacts;
- configure and install WinSW services and Scheduled Tasks where applicable;
- enroll the workstation/user overlay;
- install supported harness integrations for the selected Windows account;
- generate local DPAPI-protected keys in the user's context when that custody
  mode is selected;
- exchange only the public key and proof of possession with dossier/regista;
- show a deterministic dry-run and require confirmation before acting;
- conclude with component health, lock check, and a dossier link.

### Phase 3 — Apply, repair, and recovery

- validate and apply an approved signed configuration bundle from dossier;
- import a signed apply receipt back into the suite record;
- repair owned files/services without clobbering unrelated state;
- produce a sanitized support bundle;
- rehearse and apply an upgrade;
- guide backup restore and cryptographic verification;
- make destructive or irreversible operations explicit and separately
  authorized.

The Setup surface exposes only allowlisted operations. It has no arbitrary
shell, environment editor, SQL console, or secret-value form.

## 6. Work plan

### Phase 0 — Freeze contracts and UI skeleton

#### WI-0.1 — Human-surface registry

Create a machine-readable registry of area, route, role, owning component,
provider operation, risk class, status vocabulary, proof, and support level.
Dossier navigation, documentation, and golden-journey probes validate against
the registry.

#### WI-0.2 — Replaceable dossier shell

Land dossier Plan 024's semantic shell, route/view-model contracts, page-state
fixtures, and static reference prototype. The skeleton fixes information
architecture, accessibility landmarks, states, and component boundaries—not
final typography, color, spacing, or brand treatment.

#### WI-0.3 — Windows setup contract

Version the preflight/plan/apply/receipt protocol used by both CLI and Setup UI.
The UI is a client of the same deterministic orchestration functions; no action
exists only behind a button.

### Phase 1 — Daily team product

Complete Work, Review, Knowledge, Activity, Entra sign-in, project access, and
ordinary signing-identity journeys. Remove or mark development-only any
standalone viewer that duplicates dossier without its authorization model.

**Exit:** two Entra users on Windows complete start-project, mixed human/agent
work, knowledge reuse, independent review, and signing identity journeys from
published artifacts.

### Phase 2 — Evidence and protected identity

Complete verified activity coverage, case-bound evidence, offline export,
principal enrollment/rotation/revocation, offboarding, and genuine two-person
break-glass.

**Exit:** an auditor completes a scoped offline verification and two distinct
administrators complete a protected key lifecycle action with step-up and exact
digest approval.

### Phase 3 — Operations and configuration

Complete read-mostly estate inventory, proof freshness, protection, delivery,
drift, capacity, configuration draft/diff/approval, signed deployment bundle,
and apply receipt.

**Exit:** an operator identifies and repairs an injected drift and delivery
failure without consulting component source or handling a secret value.

### Phase 4 — Windows installation and recovery

Qualify clean install, rerun/no-op, per-user onboarding, harness wiring, upgrade,
repair, backup, restore, verification, uninstall, and in-place dogfood upgrade on
supported Windows client and service-host configurations.

**Exit:** a Windows administrator with no suite-development background follows
the shipped surface and documentation to a green supported profile, then
recovers from an injected failed upgrade and corrupted backup.

### Phase 5 — Human qualification

- WCAG 2.2 AA automated and manual checks on critical journeys;
- keyboard-only and screen-reader qualification;
- 200% zoom, narrow viewport, high contrast, reduced motion, and print/PDF;
- slow-network and unavailable-provider states;
- authorization, CSRF, XSS, SSRF, confused-deputy, approval-replay, secret
  reflection, and stale-state adversarial tests;
- usability runs with collaborator, reviewer, operator, and auditor personas;
- documentation tested as a user interface.

## 7. Full v1 completion gate

The human product is v1 only when:

1. Every applicable Profile A/B journey is complete through supported public
   surfaces on Windows; Profile C features claimed supported also pass.
2. Dossier is the one normal team URL and no required journey depends on a
   second unauthenticated/local web viewer.
3. Entra identity, project authorization, step-up, key lifecycle, and
   offboarding are coherent and fail closed.
4. Work, knowledge, activity, evidence, operations, and administration use
   consistent identifiers, status, and freshness semantics.
5. The browser never handles private keys, secret values, arbitrary host
   commands, or root deployment authority.
6. Agent Suite Setup completes clean install and recovery on Windows from the
   exact candidate artifacts.
7. Static/offline evidence remains independently usable without dossier or
   production credentials.
8. Unknown, degraded, unsupported, stale, partial, and pending states are never
   rendered as success.

## 8. Explicit non-goals

- a separate UI per component;
- a Windows desktop clone of dossier;
- remote arbitrary command execution or fleet management;
- browser-based secret/private-key entry;
- employee productivity scoring or covert surveillance;
- replacing component CLIs or public APIs;
- freezing final visual branding before the functional and accessibility
  contracts are qualified.
