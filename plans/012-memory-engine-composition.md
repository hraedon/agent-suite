# Plan 012 — Compose and qualify pluggable memory without thickening the suite

**Status:** Proposed 2026-07-11.
**Author:** GPT-5.6 Sol, coordinating agent-notes Plans 020/021 with the suite
v1 contracts and deployment boundary.
**Depends:** agent-notes Plan 020, agent-suite Plans 008 and 009.
**Strategic role:** Let an operator deploy and verify a qualified learned-memory
engine while keeping agent-suite a thin orchestrator and regista the exact
signed knowledge authority.

## Decision

The memory engine is a **nested extension of agent-notes**, not a seventh fixed
suite component. Agent-notes owns the provider protocol, adapter, provider CLI,
scope mapping, and health detail. Agent-suite only:

- carries provider selection and secret references;
- calls agent-notes' idempotent provider commands;
- aggregates nested health;
- pins the qualified provider/adapter/protocol set;
- proves the selected deployment through the golden journey;
- documents backup, rebuild, upgrade, and rollback.

Agent-notes remains the required agent face. Regista remains required for exact
signed work and knowledge in the existing assurance profiles. Profiles gain
capability requirements alongside component requirements; an available process
is not proof that recall, isolation, or indexing is healthy.

Self-hosted Hindsight is the provisional recommended learned-memory engine from
agent-notes Plan 020. The minimal/offline deployment stays native. Suite code
must contain no Hindsight-specific bootstrap or doctor branch: the selected
adapter is responsible for conforming to agent-notes' provider CLI.

## Ground truth and overlap

- `data/contracts/knowledge.json` v1 freezes the canonical entity split:
  breadcrumbs with lifecycle are work items; memories/reflections are signed
  notes; embeddings are projections.
- Plan 009 §7.3 still calls that split unresolved. The entity split is now
  settled; what remains unsettled is which learned-memory engine implements the
  projection/recall plane.
- Plan 009 WI-1.2 continues to own exact signed note parity, links, and the
  cross-face knowledge journey. This plan does not duplicate that work.
- `components.py` and deployment profiles enumerate six concrete components.
  Provider extensions need compatibility and health metadata without turning
  every possible backend into a permanent suite member.
- Backup/restore currently protects regista and component state. A learned
  engine sourced only from exact signed notes can be rebuilt, but its indexing
  state and any provider-only derived artifacts must be reported honestly.

## Principles

1. **Thin orchestration.** If agent-notes does not expose a provider operation,
   the feature is added there rather than reimplemented in agent-suite.
2. **Capabilities, not brand inference.** Doctor and profiles consume declared,
   tested capabilities and live state.
3. **No secret values.** Suite config and lock files carry secret references or
   non-secret digests only.
4. **No silent fallback.** A configured required provider outage is unhealthy;
   native exact reads remaining available does not make learned recall green.
5. **Canonical versus rebuildable.** Runbooks and proofs distinguish signed
   knowledge loss from a stale, empty, or lost derived index.
6. **No mandatory cloud/model provider.** The minimal profile remains operable
   without an external memory or inference service.

## Phase 0 — Knowledge and memory contracts v2

### WI-0.1 — Separate exact knowledge from learned memory

Revise the knowledge contract and add a versioned memory-provider contract. The
knowledge contract continues to define work-item versus signed-note authority.
The provider contract defines:

- repository and engine roles;
- capability names and protocol version;
- project/workspace/user/agent/session scopes;
- ingest operation and indexing states;
- recall origin/provenance classes;
- exact-source and synthesis capabilities;
- deletion receipts and cascade reporting;
- authority and degraded/failure semantics;
- health and version shape.

**AC:**

- v1→v2 compatibility and fixture migration are explicit.
- Contract validation rejects unknown status/capability values, missing
  authority, success for unsupported operations, and a learned result presented
  as canonical truth.
- The contract can describe native, self-hosted Hindsight, and a graph-oriented
  provider without provider-specific fields in the common section.
- Plan 009 §7.3 is amended to call the entity split settled and the learned
  engine seam open.

### WI-0.2 — Qualification and support levels

Define `experimental`, `qualified`, `recommended`, and `unsupported` memory
provider states using agent-notes Plan 020's conformance and corpus evidence.

**AC:**

- A support level names tested provider, adapter, protocol, deployment mode,
  model configuration class, platforms, proof date, and known gaps.
- `recommended` requires the live self-hosted proof, zero isolation/deletion
  failures, and the predeclared material quality advantage over native.
- A cloud deployment is qualified separately from self-hosted and is never
  inferred equivalent.

## Phase 1 — Configuration and bootstrap composition

### WI-1.1 — Provider-neutral suite configuration

Add provider selection, deployment endpoint, model/privacy posture, and secret
references to suite configuration. Keep exact repository and learned engine
selection distinct.

**AC:**

- Native/minimal and recommended learned-memory examples use placeholders only.
- Configuration validation rejects contradictory authority or scope mappings.
- Provider credentials use regista secret-backend references and are resolved
  only by the component/adapter that consumes them.
- Config output and dry-run redact secrets and resolved credential values.

### WI-1.2 — Delegate provision/configure/uninstall

Insert a memory-provider step after regista and the agent face are available.
Call `agent-notes memory-provider provision|configure` (or the final contracted
verbs); do not invoke Docker, Hindsight, Mem0, or another provider directly.

**AC:**

- Native and selected-default clean installs, reruns, dry-runs, and uninstall
  ownership are tested with stubbed component CLIs.
- Missing adapter, incompatible provider, absent secret reference, and failed
  provisioning stop the required path with actionable detail.
- Optional learned memory may be skipped by profile; required learned memory may
  not be smoothed into a native success.

## Phase 2 — Nested health and capability-aware profiles

### WI-2.1 — Memory section in agent-notes doctor

Aggregate the agent-notes provider report without parsing provider-native
output in the suite.

**AC:**

- The nested report includes repository/engine authority, provider and adapter
  versions, protocol, reachability, capabilities, capture/recall state, indexing
  backlog/freshness, scope mapping, model/privacy posture, and remediation.
- Absent optional engine, unavailable required engine, capture-only,
  recall-only, stale index, failed ingestion, and unsupported synthesis are
  distinct states.
- Human and JSON doctor output agree; empty/unconfigured deployments are not
  inferred healthy.

### WI-2.2 — Capability requirements alongside components

Retain component requirements for deployment topology, but add required feature
capabilities such as exact durable knowledge, agent recall, and—where selected—
learned/temporal recall.

**AC:**

- Profile classification cannot be satisfied by component presence when a
  required capability is unhealthy or unsupported.
- The minimal/offline profile is valid with native recall.
- The recommended learned-memory profile requires a qualified engine and live
  recall/indexing health.
- Managed-provider absence or authentication failure is reported distinctly
  from an uninstalled local service.

## Phase 3 — Compatibility lock and upgrades

### WI-3.1 — Provider extension pins

Extend `SUITE.lock` with a provider-extension section separate from the static
six component pins:

- provider name and version/image digest;
- adapter name and version;
- memory protocol version;
- deployment mode and support level;
- non-secret configuration digest;
- qualification evidence identifier/date.

**AC:**

- Generate, parse, round-trip, drift, and backward-compatibility tests cover
  locks with and without memory extensions.
- Lock generation never shells provider-specific commands from suite core; it
  consumes agent-notes' versioned provider report.
- An unknown provider version, protocol mismatch, changed deployment mode, or
  adapter drift is named rather than folded into ordinary component drift.

### WI-3.2 — Upgrade and rollback gates

Gate provider/adapter upgrades on the memory conformance subset and exact-note
interop journey. Rollback changes the learned engine without rewriting signed
knowledge.

**AC:**

- Upgrade dry-run identifies provider data migrations and whether rollback is
  lossless, rebuild-based, or unsupported.
- Failed qualification leaves the prior provider serving and the signed
  repository unchanged.
- Rollback to native is always available when exact knowledge survives, with
  indexing degradation reported until native rebuild completes.

## Phase 4 — Golden journey and operations

### WI-4.1 — Extended GJ-3 proof

Extend the knowledge journey without replacing Plan 009 WI-1.2:

1. file a signed note through agent-notes;
2. observe provider ingestion pending then indexed;
3. recall learned context with a source reference;
4. read the exact signed note through the human face;
5. delete/supersede according to policy and verify provider cascade;
6. prove another project cannot retrieve it.

**AC:**

- Native baseline and the selected recommended provider both run in CI or the
  recorded support matrix.
- Provider outage proves exact note readability while learned recall is red.
- A decoy note in another project fails the isolation negative.
- Synthesized output, if tested, is labelled derived and cannot satisfy the
  exact-note assertion.

### WI-4.2 — Backup, rebuild, and recovery posture

Update deployment and disaster-recovery documentation for each state class:

- canonical signed knowledge;
- reproducible source documents/outbox checkpoints;
- rebuildable index and extracted facts;
- provider-only mental models or feedback;
- externally hosted state with its own backup/export contract.

**AC:**

- A restore drill rebuilds a clean learned engine from signed note export and
  verifies source IDs, scope isolation, and recall readiness.
- Doctor distinguishes rebuilding/stale from data loss.
- If provider-only derived state is not backed up, the runbook says so plainly
  and does not call the restore complete until the declared recovery target is
  met.
- Operator docs include model/content exposure, deletion, retention, cost, and
  provider exit/export procedures.

## Sequencing

Agent-notes Plan 020 Phase 0 owns the protocol and evidence; this plan consumes
them. Contract v2 lands before suite configuration. Bootstrap and nested doctor
land before lock/upgrade support. No provider becomes recommended until the
extended golden journey and recovery proof are recorded.

Plan 021's `WorkProvider` is intentionally separate. It requires no suite-level
provider selection now; Gas Town remains an external orchestrator unless a
future deployment triggers its adoption spike.

## Non-goals

- Reimplementing memory ingestion, retrieval, provider SDKs, or provider health
  probes in agent-suite.
- Adding every provider to the static component tuple.
- Making learned memory authoritative work or knowledge state.
- Installing Gas Town or another agent control plane.
- Requiring Hindsight, a cloud service, or an inference provider for the
  minimal suite.
