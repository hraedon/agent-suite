# Plan 016 — NIST AI RMF operational profile for the agent suite

**Status:** Proposed — planning baseline drafted 2026-07-17.  No conformance,
compliance, certification, or trustworthiness claim is made by this plan.
**Owner:** agent-suite owns the cross-suite profile, evidence composition, and
release gates.  Each component continues to own its domain controls.
**Depends:** agent-suite Plans 008, 009, 011, 013, 014, and 015; the security,
privacy, provenance, identity, capability, delivery, and human-interface plans
in the constituent repositories.
**Normative baseline:**

- [NIST AI 100-1, Artificial Intelligence Risk Management Framework 1.0](https://doi.org/10.6028/NIST.AI.100-1), January 2023;
- [NIST AI RMF Playbook](https://airc.nist.gov/airmf-resources/playbook/),
  used as voluntary implementation guidance rather than as a checklist;
- [NIST AI 600-1, Generative Artificial Intelligence Profile](https://doi.org/10.6028/NIST.AI.600-1),
  July 2024, because the suite deploys and coordinates generative-model agents.

NIST is revising AI RMF 1.0.  The profile therefore records the exact framework
and profile versions it maps, and revisits the mapping when NIST publishes a
revision.  A moving web page never silently changes a released suite claim.

## 1. Decision and intended outcome

The suite will maintain a **bounded AI RMF Current Profile and Target Profile**
for the agentic systems it deploys or operates.  It will implement and produce
evidence for the NIST outcomes that are plausibly within the suite's control,
provide supporting evidence for outcomes shared with an operator or model
provider, and explicitly identify outcomes that require organizational,
sector-specific, human-subject, or model-developer work outside this software.

The useful outcome is not a badge.  It is a repeatable answer to these questions:

1. Which AI systems, models, harnesses, tools, data paths, people, and third
   parties are in this deployment?
2. What are they intended and prohibited from doing, for whom, and under what
   human oversight and authority?
3. What risks and beneficial uses have been mapped for each context?
4. Which risks are measured, by what test, in what deployment-like conditions,
   against what threshold, and with what uncertainty?
5. Who accepted each residual risk, what controls are active, and when must the
   decision be revisited?
6. How are errors, incidents, appeals, provider changes, unsafe behavior, and
   decommissioning handled and evidenced?

The profile complements Plan 015's production release gates.  It does not create
a second release board, claims ledger, incident store, policy engine, or UI.

## 2. Claim discipline

Every AI RMF mapping record has two independent dimensions:

- **relationship:** `direct`, `supporting`, `organizational`, `provider`,
  `conditional`, or `not_applicable`;
- **evidence state:** `implemented`, `partial`, `planned`, `external_evidence`,
  `unmeasured`, or `not_applicable`.

`direct` means the suite or one of its components enforces or measures the
outcome.  `supporting` means the suite supplies evidence or workflow but another
actor retains responsibility.  Neither word means NIST has assessed or endorsed
the implementation.

No outcome becomes green merely because:

- a policy document exists;
- a model provider makes a general marketing claim;
- a unit test exercises a mock rather than the released model/harness/system;
- provenance records that an action happened without establishing that it was
  authorized, safe, accurate, fair, or appropriate;
- an unmeasurable risk is absent from a dashboard;
- an operator has not yet filled an organizationally owned field.

Unknown, unavailable, stale, provider-undisclosed, and not-evaluated are distinct
states.  The profile must not collapse them into `pass`.

## 3. System boundary

### 3.1 In scope

The target profile covers the deployed **agentic application system**, including:

- selected model and model service, version/alias, access terms, and known
  provider disclosures;
- harness, plugin, system prompt/instructions, skills, MCP servers, tools,
  capability grants, secret injection, sandbox, and network policy;
- agent, subagent, human principal, delegation, session, work-item, and review
  relationships;
- prompts and model outputs to the extent the configured privacy/retention mode
  permits them to be observed, plus digest-only evidence where content capture
  is not permitted;
- input, output, memory, knowledge, provenance, notification, audit, export, and
  deletion/retention data flows;
- installation, configuration, change, monitoring, incident, recovery,
  deactivation, and decommissioning workflows;
- third-party models, APIs, packages, plugins, marketplaces, data sources, and
  service dependencies used by the deployed system;
- the human-facing statements, warnings, approvals, appeals, and evidence used
  to supervise the system.

Profiles A, B, and C remain separate deployment contexts.  Optional ACB or wake
capabilities cannot silently expand the authority or risk classification of a
Profile A/B deployment.

### 3.2 Outside the software's authority

The suite cannot independently establish the following unless the relevant
model provider supplies sufficiently specific evidence or the operator performs
an external assessment:

- foundation-model training-data composition, consent, representativeness,
  provenance, labor practices, or embedded intellectual-property rights;
- intrinsic model fairness across every population, language, and use case;
- complete model explainability or interpretability;
- model-training energy, water, and carbon impact;
- undisclosed model weights, safety training, internal evaluations, or provider
  incident history;
- legal conclusions, sector-specific compliance, civil-rights impact judgments,
  or approval to conduct research involving human subjects;
- executive accountability, workforce diversity, organizational culture, or
  personnel competence merely because a configuration field was completed.

The suite can inventory disclosures, require evidence before a use case is
approved, track gaps, restrict tools and data, run application-level tests,
record decisions, and fail closed.  It must label those as supporting controls,
not substitutes for the missing assessment.

### 3.3 Prohibited architectural shortcuts

- No AI/model call may decide whether an AI RMF control passed, approve its own
  residual risk, verify its own provenance, or authorize a protected mutation.
- No second event store or policy truth is added to agent-suite.  Durable risk,
  decision, incident, approval, and review records use versioned regista public
  contracts.
- No component-private database access or private-module import is introduced.
- No prompt or output containing a secret becomes compliance evidence.
- No blanket content capture is enabled in the name of auditability.  Privacy,
  purpose limitation, minimization, encryption, retention, and disclosure rules
  still govern evidence collection.

## 4. Generative-AI risks to map

NIST AI 600-1 identifies twelve risks unique to or exacerbated by generative AI.
Every deployed use-case profile must assess all twelve, while the depth of
treatment remains proportional to context and authority.

| GAI risk | Plausible suite responsibility | Boundary |
|---|---|---|
| CBRN information or capabilities | Prohibited-use policy, tool/data isolation, high-risk scenario tests, incident/deactivation path | Intrinsic model capability and specialist CBRN evaluation require provider/domain expertise |
| Confabulation | Grounded-task tests, citation/source checks where applicable, human confirmation, outcome/error sampling, warnings | No universal factuality claim across open-ended tasks |
| Dangerous, violent, or hateful content | Use-case restrictions, provider-policy recording, abuse tests, escalation and incident handling | Primary model moderation remains provider-dependent |
| Data privacy | Data-flow inventory, minimization, secret boundary, retention, encryption, disclosure authorization, leakage tests | Training-data privacy requires provider evidence |
| Environmental impacts | Record model/service and available usage/energy disclosures; permit budget or model-choice policy | Training footprint and many inference metrics are provider-held |
| Harmful bias and homogenization | Use-case-specific subgroup/language tests, accessibility review, feedback and appeal, known-gap register | No context-free or universal fairness claim |
| Human-AI configuration | Clear agent identity, authority and limitation display, human gates, anti-overreliance UX, training material, override | Human factors require real-user evaluation, not code inspection alone |
| Information integrity | Signed event lineage, source/citation preservation, content provenance, uncertainty display, independent verification | Provenance proves origin/history, not truth |
| Information security | Threat models, least privilege, sandbox/network/tool policy, secret-safe injection, prompt-injection tests, supply-chain controls | Model-provider infrastructure remains shared responsibility |
| Intellectual property | Input/source/license inventory, output-use policy, provider terms, incident/takedown workflow | The suite cannot adjudicate copyright or guarantee non-infringement |
| Obscene, degrading, or abusive content | Strict prohibited-use policy, provider controls, access restrictions, testing and escalation | Specialist safeguarding and legal processes remain organizational/external |
| Value-chain and component integration | Immutable lock, SBOM, plugin/provider identity, versioned contracts, disclosure inventory, change monitoring, fallback | Provider internals remain unknown unless disclosed |

## 5. Target control and evidence model

### 5.1 Machine-readable profile artifacts

Agent-suite will define schemas and generated human views for:

- `data/ai-rmf/framework-baseline.json` — exact NIST document versions and the
  seventy-two AI RMF Core subcategories;
- `data/ai-rmf/current-profile.json` — observed relationship and evidence state,
  owner, proof, freshness, limitation, and residual risk for every subcategory;
- `data/ai-rmf/target-profile.json` — selected target outcomes by deployment
  profile and risk tier;
- `data/ai-rmf/system-inventory.json` — system/use-case/model/provider/harness/
  plugin/tool/data-flow inventory with immutable release identity where known;
- `data/ai-rmf/risk-register.json` — stable risk IDs, context, affected actors,
  likelihood, impact, uncertainty, controls, metrics, owner, treatment, review
  date, incidents, and accepted residual risk;
- `data/ai-rmf/evaluation-catalog.json` — scenario, dataset/fixture, metric,
  threshold, environment, independence, cadence, and evidence artifact;
- `data/ai-rmf/organizational-actions.json` — human-owned legal, training,
  leadership, diversity, human-subject, procurement, and stakeholder actions
  that software cannot complete.

Generated artifacts are reproducible from schemas and source records.  Real
deployment identifiers, prompts, outputs, personal data, secrets, and incident
details remain in the protected deployment evidence store, not committed files.

### 5.2 Stable public surfaces

The intended operator surfaces are:

```text
agent-suite ai-risk inventory --profile B --json
agent-suite ai-risk map --use-case <id> --json
agent-suite ai-risk evaluate --use-case <id> --candidate <lock> --json
agent-suite ai-risk status --profile B --json
agent-suite ai-risk evidence --candidate <lock> --output <bundle>
```

These commands compose component public contracts.  They do not infer model
quality from package health or make model calls in the classification path.
`status` is read-only.  Acting changes use existing plan/diff/approval/apply/
receipt patterns and explicit human authority.

Dossier eventually renders the same providers as an **AI risk** area under its
Operations/Administration surfaces: inventory, use-case cards, risk register,
evaluation results, incidents/appeals, pending decisions, provider changes, and
decommission state.  Dossier does not recompute verdicts.

### 5.3 Evidence requirements

Every implemented target outcome points to evidence proportional to its claim:

- schema/contract tests for shapes and closed vocabularies;
- property and adversarial tests for invariants and fail-closed behavior;
- recorded-real fixtures for harness/provider payload fidelity;
- candidate-bound integration tests for composed behavior;
- live, session-correlated proofs for model/harness/tool behavior that mocks
  cannot establish;
- operator exercises for incident response, override, rollback, provider
  failure, and decommissioning;
- independent review for high-risk mappings and residual-risk acceptance;
- sanitized, signed evidence bundles with freshness, environment, model,
  provider, harness, component lock, configuration digest, and evaluator identity.

An evaluation result is stale after a material model alias/version, system
prompt, plugin, tool, data source, policy, or deployment-context change unless
the risk owner documents why re-evaluation is unnecessary.

## 6. Phase 0 — Govern: freeze the profile and accountability model

### WI-0.1 — Encode the AI RMF baseline and honest crosswalk

Encode all seventy-two AI RMF 1.0 Core subcategories, NIST source/version, suite
relationship, evidence state, component owner, existing evidence, limitation,
and target profile.  Seed the Current Profile from executable repository and
deployment observations; do not convert plan text into `implemented`.

Add a framework-version watcher that reports a new NIST publication as review
required, never auto-migrates meanings, and keeps released profiles reproducible.

**AC:** schema validation rejects unknown/missing subcategories and unrecognized
states; every subcategory appears exactly once; generated Markdown round-trips
from JSON; a test proves `planned` and `external_evidence` cannot count green.

### WI-0.2 — Inventory systems, models, authority, and dependencies

Extend candidate inventory with use-case ID, model/provider identifier and
disclosure version, harness/plugin/tool versions, system-instruction digest,
MCP/capability grants, sandbox/network policy, knowledge/memory sources,
retention mode, human owner, and upstream/downstream service dependencies.

Model aliases such as `latest` are observations, not immutable identities.  If a
provider will not expose a stable model revision, record that limitation and
trigger re-evaluation on observed alias or behavior change.

**AC:** inventory is secret-safe, profile-aware, diffable, and fails closed on a
required unknown owner/model/provider/tool authority; unrelated user plugins and
configuration remain outside suite ownership but appear as named external risk.

### WI-0.3 — Define risk taxonomy, tiers, tolerance, and decision authority

Adopt a small, documented ordinal likelihood/impact/uncertainty method.  Define
use-case tiers based on affected people, reversibility, data sensitivity, tool
authority, external side effects, autonomy, scale, and availability of meaningful
human review.  Define prohibited contexts and non-waivable controls separately
from tolerable residual risk.

Suggested initial tiers:

- **R0 — advisory sandbox:** no sensitive data, durable mutation, external side
  effect, or reliance without human verification;
- **R1 — bounded workflow:** reversible writes inside an authorized project,
  explicit review and complete provenance;
- **R2 — consequential/privileged:** sensitive data, credentials, production
  changes, external communications, protected decisions, or difficult reversal;
- **R3 — prohibited pending specialist approval:** safety-critical, rights-
  determining, high-impact domain, CBRN, abusive-content, or other context beyond
  the suite's qualified evidence and organizational authority.

**AC:** every use case has one tier and owner; R2 requires independent evaluation,
human approval, incident/deactivation readiness, and explicit residual-risk
acceptance; R3 cannot be enabled by a config-only override.

### WI-0.4 — Assign roles, review cadence, and organizational actions

Publish a RACI-like assignment for system owner, use-case owner, risk owner,
security/privacy reviewers, TEVV lead, incident commander, model/provider owner,
human approver, auditor, and decommission owner.  Record separation-of-duties
requirements and review cadence by risk tier.

Provide operator templates for legal applicability, AI risk training, affected-
actor engagement, accessibility, workforce/diversity considerations, human-
subject review, procurement, and executive acceptance.  These remain incomplete
until a named human or organization supplies evidence.

**AC:** no agent may approve its own risk, evaluation, or protected deployment;
expired role/training/acceptance evidence is visible; absent organizational
evidence cannot be synthesized by the software.

**Phase 0 exit:** the exact framework is pinned; all systems and use cases have
owners and preliminary tiers; all seventy-two outcomes are mapped honestly;
organizational work is visible rather than silently omitted.

## 7. Phase 1 — Map: establish context, impact, and value chain

### WI-1.1 — Use-case and human-oversight cards

For each use case, record intended purpose, beneficial use, prohibited/misuse
cases, users and affected actors, deployment context, assumptions, knowledge
limits, expected output use, non-AI alternative, human decision/override point,
appeal path, required proficiency, and go/no-go owner.

The card must distinguish assistance from decision authority and state when a
human is expected to verify facts, code, citations, tool arguments, side effects,
or communications.

**AC:** an operator can answer what the agent may decide or execute without
reading prompts or source code; changing authority or context invalidates the
prior risk decision.

### WI-1.2 — Data, content, and authority-flow maps

Generate a data-flow and authority-flow record from model input through harness,
memory/knowledge, tools/MCP, ACB, regista, cairn, notifications, dossier, exports,
and retention/deletion.  Classify personal, sensitive, secret, proprietary,
untrusted, model-visible, logged, encrypted, digest-only, and externally sent
data at each boundary.

Model prompt injection and confused-deputy paths across retrieved text, tool
output, plugins, wake messages, memory, and web/browser content.  Enumerate every
side-effecting capability and the principal/policy/human gate that authorizes it.

**AC:** no sensitive or acting path is absent; an untrusted content source cannot
silently become instruction or authority; secrets never enter model-visible
context or committed evidence.

### WI-1.3 — Third-party and model-provider evidence register

Bind the release SBOM/lock and plugin marketplace identity to a provider register
covering model/service terms, data-use and retention statements, model/system
cards, evaluation reports, incident/security contact, change notice, regional
processing, subprocessors where applicable, fallback, and exit/deletion path.

Provider statements are attributed, dated evidence, not suite assertions.
Missing disclosures become explicit procurement and residual-risk findings.

**AC:** mutable model aliases, plugin-name collisions, unpinned dependencies,
unknown provider changes, expired evidence, or unavailable critical fallbacks
cannot report target-profile green.

### WI-1.4 — Impact, stakeholder feedback, and appeal design

Create an impact-assessment template that covers the twelve GAI risks, security,
privacy, accessibility, affected groups/languages, labor/workflow displacement,
error costs, scale, reversibility, benefits, non-AI baseline, and unknowns.

Use dossier/regista public workflows for feedback, problem reports, appeals,
adjudication, and response.  Protect reporters and sensitive incident content;
do not place it in public notifications or ordinary model context.

**AC:** a report or appeal is durable, assigned, acknowledged, adjudicated by an
authorized human, linked to the affected use case/evaluation/release, and able to
trigger risk re-ranking or deactivation.

**Phase 1 exit:** every supported use case has an approved context card, impact
assessment, data/authority map, provider evidence register, and usable feedback/
appeal path.

## 8. Phase 2 — Measure: candidate-bound TEVV and monitoring

### WI-2.1 — Evaluation catalog and deployment-like scenario packs

Define reusable, versioned scenario packs by use case and risk tier.  Applicable
packs cover:

- task validity, reliability, confabulation, citation/source fidelity, and
  graceful uncertainty;
- authorization, least privilege, sandbox/network boundaries, tool argument
  integrity, replay, confused deputy, and safe failure;
- direct and indirect prompt injection, data/secret exfiltration, malicious tool
  output, poisoned memory/knowledge, and plugin/provider substitution;
- privacy leakage, retention/deletion, disclosure, and cross-project/principal
  isolation;
- use-case-specific subgroup, language, accessibility, harmful-content, refusal,
  and overreliance cases where relevant;
- model/provider unavailability, latency, changed behavior, rollback/fallback,
  and deactivation;
- provenance completeness, model/harness/session/work correlation, truncation,
  and offline verification.

**AC:** each test names the mapped risk, data/fixture provenance, metric,
threshold, expected failure mode, deployment-like environment, and limitations;
synthetic fixtures never masquerade as affected-community evidence.

### WI-2.2 — Metrics, thresholds, uncertainty, and unmeasured risk

Select the smallest meaningful quantitative and qualitative metrics for each
high-priority risk.  Include false-positive/negative tradeoffs, sampling rules,
confidence or uncertainty where meaningful, subgroup denominators, and the human
baseline or non-AI comparison when one exists.

Maintain an `unmeasured` register for intrinsic or emergent risks that lack a
sound method.  Compensating controls and conservative deployment limits may be
used, but absence of a metric is never equivalent to absence of risk.

**AC:** thresholds are approved before the release test; post-hoc threshold
changes are signed decisions; no aggregate score hides a failed non-waivable
control or materially worse subgroup/context.

### WI-2.3 — Recorded-real and live agentic proofs

Run candidate-bound evaluations against the actual supported model, harness,
plugins, policies, tools, and representative deployment configuration.  Capture
model/provider identity as precisely as the provider permits and correlate the
session, turn, tool call, side effect, work item, principal, delegation, and
evaluation case.

Use recorded-real payloads for deterministic regression, then retain live proofs
for claims mocks cannot establish.  Inject concurrent decoys, missing hooks,
provider drift, and unobservable actions so silence is tested as a finding.

**AC:** the evidence proves the released composition, not merely each component;
an unrelated event or synthetic plugin cannot satisfy a component/live-proof AC.

### WI-2.4 — Independent and adversarial evaluation

Apply the existing adversarial-review and human-gate model to TEVV.  R2 results
require a qualified reviewer who did not build the evaluated control.  Maintain
red-team cases for prompt injection, privilege escalation, evidence forgery,
misleading explanations/citations, unsafe tool use, sensitive-data extraction,
provider substitution, and bypass of human approval.

Specialist domains, affected communities, accessibility users, legal/privacy
reviewers, or safeguarding experts participate where the context requires them;
the suite records their evidence but does not impersonate them.

**AC:** findings create owned work and cannot be closed by the evaluated agent;
critical/high failures block the applicable target profile unless a documented
policy explicitly permits acceptance, and non-waivable risks cannot be accepted.

### WI-2.5 — Production observation and change detection

Compose privacy-preserving operational measures for failure/error rate, human
override and appeal, authorization denial, provenance coverage/degradation,
provider/model change, tool/capability drift, unusual secret access, incident
rate, latency/availability, and evaluation freshness.

Do not introduce model-scored health.  Deterministic checks and human-reviewed
samples remain separate.  Sampling content requires purpose, access control,
minimization, retention, and disclosure policy.

**AC:** material changes and threshold breaches create a durable review event,
alert the correct human through the configured delivery path, and can move the
use case to restricted or deactivated state without erasing historical evidence.

**Phase 2 exit:** every R1/R2 target use case has approved metrics, deployment-
like and adversarial evidence, known uncertainty, an unmeasured-risk record, and
production monitoring appropriate to its privacy mode.

## 9. Phase 3 — Manage: decisions, controls, incidents, and decommissioning

### WI-3.1 — Candidate go/no-go and residual-risk decisions

Add a signed, versioned decision record binding use case, context, risk register,
evaluation results, open findings, provider evidence, exact candidate lock, human
decision maker, treatment (`mitigate`, `avoid`, `transfer`, or `accept`), expiry,
and conditions of operation.

**AC:** no protected deployment proceeds on stale/missing evidence; an acceptance
cannot exceed the approver's authority or waive a prohibited/non-waivable risk;
the operator and downstream user can see material residual risks and limitations.

### WI-3.2 — Enforce proportional runtime controls

Compose existing controls by risk tier: principal identity, delegation, least-
privilege roles, ACB capability allowlists and exact child commands, secret-safe
injection, sandbox/network policy, project isolation, content/data restrictions,
human confirmation, dual control, review gates, rate/resource limits, and
fail-closed provider behavior.

Keep policy enforcement deterministic.  A model may recommend a plan but cannot
grant itself a capability, broaden its scope, approve its own output, or decide
that a control is unnecessary.

**AC:** negative tests prove every protected boundary rejects missing, stale,
wrong-principal, wrong-scope, replayed, self-approved, and provider-unknown input
for the intended reason.

### WI-3.3 — AI incident, error, feedback, and disclosure workflow

Define an AI-specific incident taxonomy connected to existing security/operations
response: harmful or unauthorized output, unsafe action, privacy/secret exposure,
rights/accessibility impact, provenance gap, provider/model change, prompt
injection, capability misuse, misleading content/citation, supply-chain event,
and systemic repeated error.

Record detection, containment, affected use cases/releases/people, evidence hold,
notification/disclosure decision, remediation, recovery, appeal/redress, and
retrospective.  Coordinate external legal or regulatory notifications through a
named organizational owner rather than embedding jurisdictional law in code.

**AC:** tabletop and injected live exercises prove report -> triage -> contain ->
notify/communicate -> recover -> retrospect -> update risk/evaluation; sensitive
incident evidence is access-controlled and ordinary alerts reveal no secret or
personal content.

### WI-3.4 — Restrict, deactivate, revoke, and decommission safely

Define reversible restriction and emergency deactivation for each layer: use
case, model/provider, harness/plugin, capability/tool, principal/key, scheduled
agent, notification route, and whole deployment.  Deactivation must work without
asking the model to cooperate.

Decommissioning covers dependency order, pending work, user notification,
provider access revocation, tokens/credentials/keys, plugin/hook removal with
ownership checks, retained evidence, personal-data deletion obligations,
exports, backups, fallbacks, and post-removal verification.

**AC:** clean and user-modified states are tested; partial/manual removal is a
conflict rather than false success; retained audit evidence remains verifiable;
provider-side deletion requiring human action remains open until evidenced.

### WI-3.5 — Third-party change, outage, and fallback management

Monitor material model/provider/plugin/service changes and incident disclosures.
Define whether each use case fails closed, becomes read-only, uses a qualified
fallback, or requires human/manual processing.  A fallback is a separately
inventoried and evaluated composition, not an interchangeable model name.

**AC:** provider outage, silent alias change, revoked plugin, incompatible API,
unavailable memory/capability, and fallback failure are exercised; no degraded
path silently increases data exposure, authority, or unsupported claims.

**Phase 3 exit:** target use cases have candidate-bound decisions and controls;
incident and appeal workflows work; unsafe systems can be independently stopped,
recovered, and decommissioned with verifiable residual state.

## 10. Phase 4 — Sustain, communicate, and independently review

### WI-4.1 — Dossier AI-risk operator and reviewer surface

Render the public providers for inventory, context cards, risk/evaluation state,
limitations, provider disclosures, pending decisions, incidents/appeals,
deactivation, and review freshness.  Use accessible server-rendered flows for
protected decisions and show the difference between model output, deterministic
system verdict, provider assertion, and human judgment.

**AC:** a non-developer reviewer can trace a deployed use case from intended use
through evidence and residual-risk decision without CLI access or private-store
queries; route visibility never substitutes for authorization.

### WI-4.2 — AI RMF evidence bundle and claims publication

Extend the release audit bundle with the pinned framework/profile, Current and
Target Profile, inventory, risk register, evaluations, decisions, provider
evidence digests, incidents/exercises, accepted limitations, and independent
verification instructions.  Publish only sanitized evidence; protected source
material remains referential and access-controlled.

The claims ledger gains narrowly worded AI RMF mappings.  Public language says
"aligned to" or "supports outcomes" with scope/version, never "NIST certified"
or blanket "AI RMF compliant."

**AC:** an independent reviewer can reproduce structural/profile verdicts and
verify signatures without production write authority; missing protected evidence
is visibly unavailable rather than represented as independently verified.

### WI-4.3 — Periodic review, training evidence, and improvement loop

Set review cadences by risk tier and triggers for re-MAP/re-MEASURE/re-MANAGE:
model/provider or prompt change, new tool/data source, context/scale expansion,
incident/appeal, material metric decline, new vulnerability or NIST revision,
expired provider evidence, and changed legal/organizational requirements.

Track role-specific training and exercise evidence as organizational artifacts.
Use retrospectives, feedback, incidents, and field measurements to create signed
work and improve scenario packs, controls, and documentation.

**AC:** stale reviews are red for R2 and plainly visible for all tiers; updates
preserve historical decisions and explain why controls or thresholds changed.

### WI-4.4 — Independent readiness review

Before a supported AI RMF-aligned profile is published, commission a reviewer
independent of the implementation work to challenge scope, missing actors and
harms, test validity, provider reliance, privacy, fairness/accessibility where
applicable, incident readiness, deactivation, and public claim wording.

**AC:** all critical/high findings are fixed or remove the affected target claim;
the final profile lists unresolved risks, organizational actions, unmeasured
outcomes, provider dependencies, and review identity/date.

**Phase 4 exit:** operators can use and sustain the profile; external reviewers
can verify the evidence boundary; published wording is no broader than proof.

## 11. AI RMF Core coverage crosswalk

This is the **target relationship**, not current implementation status.  WI-0.1
must assess the current evidence without inheriting these targets as green.

| AI RMF outcomes | Target relationship | Primary planned evidence/owner |
|---|---|---|
| GOVERN 1.1 | organizational + supporting | legal/applicability register and named counsel/compliance owner; suite records version and gaps |
| GOVERN 1.2–1.7 | direct/supporting | trustworthy-characteristic policy, tier/tolerance, signed decisions, review cadence, inventory, decommission proof |
| GOVERN 2.1 | direct | role and communication contract, regista identity/approval record |
| GOVERN 2.2–2.3 | organizational | training attestations and accountable human/executive acceptance; never agent-completed |
| GOVERN 3.1 | organizational + supporting | documented multidisciplinary/affected-actor participation; no demographic inference |
| GOVERN 3.2 | direct/supporting | human/agent role, authority, oversight, override, appeal, dual-control contracts |
| GOVERN 4.1–4.3 | direct/supporting | adversarial review, impact/risk records, TEVV catalog, incident/error sharing |
| GOVERN 5.1–5.2 | supporting | feedback/appeal/adjudication workflow and evidence of incorporated changes |
| GOVERN 6.1–6.2 | direct/supporting | lock/SBOM/provider register, rights/data terms, provider incidents, outage/fallback exercises |
| MAP 1.1 | direct + organizational input | context/use-case card, laws/norms field, actors, benefits/harms, deployment assumptions |
| MAP 1.2 | organizational + supporting | participation record for diverse disciplines, users, accessibility and affected actors |
| MAP 1.3–1.6 | direct/supporting | mission/value, risk tolerance, requirements, socio-technical and non-AI alternative assessment |
| MAP 2.1–2.3 | direct/provider/shared | task/model classification, knowledge limits, human use, TEVV and provider-data limitations |
| MAP 3.1–3.5 | direct/supporting | benefit/cost/baseline, scope, operator proficiency, human oversight and appeal |
| MAP 4.1–4.2 | direct/supporting | component/data/provider risk map and internal control register |
| MAP 5.1–5.2 | supporting | likelihood/impact/uncertainty record, incidents, field feedback and stakeholder engagement |
| MEASURE 1.1–1.2 | direct | prioritized metrics, unmeasured register, control-effectiveness review |
| MEASURE 1.3 | supporting/organizational | independent assessor and domain/affected-actor participation evidence |
| MEASURE 2.1 | direct | versioned evaluation catalog, data/fixture provenance, tools and environment |
| MEASURE 2.2 | conditional/organizational | human-subject approval and representativeness evidence when such evaluation is undertaken |
| MEASURE 2.3–2.8 | direct/supporting | deployment-like performance, production observation, validity, safety, security, transparency/accountability tests |
| MEASURE 2.9 | provider + supporting | provider model documentation plus application-level explanations/source interpretation; limitation explicit |
| MEASURE 2.10 | direct/provider/shared | privacy assessment, flow/retention/leakage tests, provider training/data gaps |
| MEASURE 2.11 | conditional/shared | use-case-specific fairness, subgroup/language/accessibility evaluation and limitations |
| MEASURE 2.12 | provider + supporting | available provider footprint disclosure and suite usage/resource observations; unknown training impact |
| MEASURE 2.13 | direct | meta-evaluation of metric/scenario validity and independent review |
| MEASURE 3.1–3.2 | direct/supporting | runtime trend/change/emergent-risk tracking and explicit hard-to-measure register |
| MEASURE 3.3 | supporting | user/affected-actor problem, appeal, adjudication, and metric-update path |
| MEASURE 4.1–4.3 | supporting | deployment-context/domain review, field feedback, measured improvement/decline |
| MANAGE 1.1–1.4 | direct + human authority | go/no-go, prioritized treatment, response plan, downstream residual-risk communication |
| MANAGE 2.1–2.4 | direct/supporting | non-AI/fallback analysis, control maintenance, unknown-risk response, restrict/deactivate |
| MANAGE 3.1–3.2 | direct/provider/shared | continuous provider/model/plugin monitoring and re-evaluation triggers |
| MANAGE 4.1–4.3 | direct/supporting | production monitoring, override/appeal, decommission, change, incident/recovery and communication exercises |

## 12. Component ownership

| Component/actor | Owns in this plan |
|---|---|
| agent-suite | Profile schemas/crosswalk, system inventory composition, risk-tier policy, release/evaluation orchestration, status, evidence bundle, claims discipline |
| regista | Durable versioned risk/decision/incident/feedback records, principal/delegation binding, approval and review invariants, retention and export primitives |
| agent-notes | Agent-facing context/risk work and knowledge links, safe orientation, conflict/offline behavior; no parallel risk truth |
| agent-provenance (cairn) | Model/harness/session/tool/work lineage, declared coverage/degradation, privacy-aware evidence, correlated live proof and offline verification |
| dossier | Authorized human inventory/risk/evaluation/incident/appeal/decision/decommission UX and accessibility |
| ACB | Capability/tool inventory, deterministic least privilege, exact-command secret-safe execution, drift and revocation evidence |
| agent-wake | Authenticated incident/review alerts, durable delivery/retry/dead-letter and prompt-injection-safe message framing |
| model/provider | Model/system cards, data/rights/privacy/environment disclosures, intrinsic evaluations, change/incident notice and service controls |
| operator/organization | Legal applicability, risk tolerance, accountable decisions, training, procurement, affected-actor engagement, human-subject review, incident disclosure/redress |

## 13. Sequencing with Plan 015

This plan should not derail the Profile B 1.0 critical path by attempting every
organizational outcome at once.

1. **Before Plan 015 Gate 0 exits:** land WI-0.1's schemas/crosswalk and WI-0.2's
   inventory extensions so the release knows its AI composition and gaps.
2. **During Plan 015 Gates 1–2:** complete context cards, authority/data flows,
   provider register, and the R1 scenario/evidence baseline for supported Profile
   A/B journeys.
3. **During Plan 015 Gate 3:** complete R2 risk decisions, privacy/security and
   adversarial evaluation, incident/deactivation readiness, and bounded claims.
4. **During Plan 015 Gates 4–5:** exercise provider failure, live model/harness
   behavior, incident response, fallback, restore, and decommission during the
   candidate qualification and soak.
5. **After 1.0 where necessary:** expand affected-community, fairness,
   environmental, provider, and Profile C evidence without retroactively
   broadening 1.0 claims.

## 14. Minimum credible 1.0 slice

If resources force a smaller first increment, the suite must still deliver:

- exact framework/profile version and complete seventy-two-outcome crosswalk;
- AI system/model/provider/harness/plugin/tool/authority inventory;
- supported use-case cards, risk tiers, owners, prohibited uses, human oversight,
  and residual-risk decisions;
- data/secret/authority flow and prompt-injection threat model;
- candidate-bound privacy, security, authorization, confabulation/task-validity,
  provenance, and provider-failure scenario packs;
- independent review for R2 use cases;
- durable incident/appeal path and independently operable deactivation;
- third-party/model evidence register, change monitoring, and named unknowns;
- evidence bundle and public claim language that identifies all exclusions.

Bias, accessibility, harmful-content, IP, CBRN, human-subject, and environmental
work is **not globally skipped**.  It is assessed for applicability per use case;
unsupported intrinsic/provider/organizational evidence is recorded as a gap, and
the affected use case is restricted or excluded where that gap exceeds tolerance.

## 15. Definition of done

For each supported deployment profile and use case, an independent reviewer can
start from the immutable release identity and determine:

- what AI composition and authority was deployed;
- its intended/prohibited contexts, affected actors, human oversight, and
  provider dependencies;
- every mapped AI RMF outcome and twelve GAI risks, including unknown,
  unmeasured, organizational, and provider-owned portions;
- the deployment-like tests, thresholds, limitations, field observations, and
  independent challenges supporting the decision;
- the named human who approved the residual risk and the expiry/conditions of
  that approval;
- how to report or appeal harm, investigate evidence, restrict or deactivate the
  system, recover, and decommission it;
- why each public trustworthiness statement is no broader than the evidence.

The profile is successful when it makes risk ownership and evidence operational,
keeps unsupported claims out of the product, and causes unsafe or insufficiently
understood deployments to stop or narrow.  It is not successful merely because
all framework rows contain text.
