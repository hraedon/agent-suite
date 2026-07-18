# Plan 017 — Per-agent credential isolation

**Status:** Proposed 2026-07-18.
**Owner:** agent-suite owns the cross-suite credential-isolation profile,
bootstrap composition, doctor/lock evidence, and migration sequencing. Secret
issuance and enforcement remain with the selected backend and target service;
components consume public identity/secret contracts rather than suite internals.
**Depends:** regista per-principal signing and secret-resolution contracts,
agent-capability-broker's gated credential execution surface, agent-notes Plan
022, and the suite's multi-user, capability, identity, and production plans.
**Amends:** the blueprint's shared per-project service-role posture and the
current Vault/AKV/Windows runbooks. A shared project authorization role may
remain, but runtime login credentials are unique per agent or mediated by a
broker the agents cannot read.

## 1. Outcome

No two independently revocable agents receive or use the same runtime
credential merely because they belong to one human, project, team, harness, or
host.

If User A has Agent A and User B has Agent B:

- Agent A authenticates to the secret backend with a credential unique to A's
  workload;
- Agent B authenticates with a different credential;
- their signing keys, database logins, API tokens, provider credentials, and
  capability credentials are independently issued and revocable wherever the
  target supports that model;
- a credential observed by its issuer or target identifies one agent workload
  without relying on an agent-supplied `actor_id` field; and
- revoking or rotating A does not interrupt B.

The identity vocabulary exists to bind and audit those credentials. The primary
control is credential separation, not merely more descriptive identity fields.

## 2. Current gap

The suite has per-principal signing-key paths, but the surrounding access plane
is still shared in important places:

- the Vault runbook creates one suite AppRole and its hardening example grants
  that role wildcard read access to all principal paths;
- the AKV runbook grants one host Managed Identity or service principal the
  `Key Vault Secrets User` role at vault scope;
- the Windows backend relies on the Windows account's DPAPI boundary, so target
  names do not isolate two agent processes running as the same account;
- the blueprint uses one database service login per project and relies on signed
  attribution above that shared login;
- capability manifests commonly point multiple agents at one service-account
  credential; and
- a caller can select a per-principal secret path while authenticating to the
  backend as a generic suite workload.

Those patterns can prove which signing key was selected, but possession of a
generic backend or downstream credential can still let one compromised agent
impersonate or disrupt its peers. Different path names are not sufficient when
one credential can read them all.

## 3. Decision and bounded pushback

### 3.1 Default rule

**No shared agent-visible runtime credential.** A credential made available to
an agent process, its child process, or its local harness must be unique to that
agent workload and independently revocable.

Putting the same secret value under two agent-specific names, mounting one team
token into two processes, or giving two agents the same Vault/AKV identity does
not satisfy the rule.

### 3.2 Permitted brokered exception

Some external systems expose only one service credential or cannot create an
account per agent. Such a credential may be used only when:

- it remains inside an authenticated execution broker/service and is never
  returned, mounted, injected, or made readable to an agent process;
- every agent authenticates to the broker with its own credential;
- deterministic policy authorizes the exact capability and target operation;
- the broker emits an attributable request/decision/execution receipt;
- rate limits, revocation, and denial operate per agent; and
- the deployment reports that downstream attribution terminates at the broker.

The current ACB local `exec` path injects a secret into a child process. It may
inject a **unique per-agent** credential, but it is not the brokered exception
for a shared credential. A shared-only target requires an execution service that
uses the credential without exposing it to the child.

If neither unique target credentials nor a non-disclosing broker is available,
the capability is unsupported in the strict multi-agent profile. An operator
may explicitly accept a weaker `shared_credential` posture, but doctor and the
assurance profile remain degraded and cannot claim per-agent credential
isolation.

### 3.3 What need not be unique

Public keys, certificates without private material, endpoint addresses, trust
roots, model names, schemas, ordinary configuration, and read-only public data
are not runtime credentials. Shared authorization definitions such as a
Postgres group role or Vault policy template are also acceptable when each
agent has a unique authenticating credential bound to that shared role.

## 4. Credential classes and required posture

| Credential class | Target posture | Shared-agent use |
|---|---|---|
| Secret-backend authentication | Unique per agent instance | Prohibited |
| Regista signing private key | Unique key per agent credential; registered to one agent principal | Prohibited |
| Database login/token | Unique or dynamically leased per agent instance; may inherit project role | Prohibited |
| API/OAuth token | Unique client/account/token or on-behalf-of exchange bound to agent | Prohibited by default |
| Model/provider API credential | Unique project/agent key when supported; otherwise broker-only | Direct shared key prohibited |
| Memory-provider credential | Unique direct credential, or held by authenticated agent-notes service | Direct shared key prohibited |
| Capability/service-account credential | Unique account/token; shared-only secret stays inside execution broker | Direct shared key prohibited |
| Bootstrap/admin credential | Restricted provisioning identity, unavailable to agents | May administer many agents, never a runtime credential |
| Encryption/data-protection key | Service-managed; agents normally do not receive it | Outside agent credential set |
| Break-glass credential | Offline split custody and explicit emergency workflow | Never installed in an agent |

The minimum separation unit is the stable agent principal. The preferred unit
for backend authentication, database leases, and API tokens is the agent
instance, so one compromised host can be revoked without retiring the logical
agent everywhere. Multiple instance credentials may bind to one agent principal
only through explicit enrollment and remain distinguishable by `credential_id`.

## 5. Credential binding contract

Every non-public credential has non-secret registry metadata:

- stable `credential_id` assigned by its issuer;
- `agent_principal_id` and, where applicable, `agent_instance_id`;
- delegating human principal and organization, as metadata rather than the
  authenticating subject;
- credential class, issuer/backend, target service, and allowed capabilities;
- authentication method and assurance level;
- issue, expiry, rotation, and revocation timestamps;
- secret-reference digest or issuer object ID, never the secret value;
- whether the target credential is `direct_unique`, `dynamic_unique`,
  `brokered_shared`, or prohibited `shared_agent_visible`;
- policy/version and provisioning receipt.

The binding is established during trusted provisioning. A prompt, harness
configuration, environment variable, requested secret path, or API body cannot
change the authenticated credential's agent binding.

An agent operation records or correlates:

```text
agent_principal_id
agent_instance_id
credential_id
issuer authentication subject / audit event
target-side account, token, lease, or broker receipt
session/work/capability correlation
```

Secret values and raw bearer tokens never enter this record.

## 6. Backend-specific target profiles

### 6.1 HashiCorp Vault

Production agents do not receive the generic suite AppRole or a token carrying a
wildcard `principals/*` policy.

Preferred authentication order depends on deployment:

1. workload identity/JWT, Kubernetes service account, cloud auth, or client
   certificate uniquely bound to the agent instance;
2. a distinct AppRole per agent instance when a native workload identity is not
   available;
3. a short-lived response-wrapped bootstrap secret used once to obtain the
   workload credential.

Each authenticated Vault entity/alias maps to exactly one agent instance and
receives policies for only:

- that agent's signing-key path;
- that agent's unique/static or dynamic capability credentials;
- explicitly granted project resources; and
- required metadata/health operations.

Example conceptual paths:

```text
secret/agent-suite/agents/<agent-uuid>/signing
secret/agent-suite/agents/<agent-uuid>/capabilities/<capability-id>
database/creds/<agent-or-project-role>     # unique lease returned per login
```

Policy templates may be shared; tokens, AppRole SecretIDs, client certificates,
signing keys, and returned database leases may not. Vault token metadata and
audit devices must expose the agent/instance binding and token accessor without
logging token values.

The bootstrap identity may create policies/AppRoles and write initial secrets,
but agents cannot obtain or inherit it. Wildcard access is confined to an
audited administrative role and is never the runtime default.

### 6.2 Azure Key Vault

One host-wide Managed Identity or service principal shared by multiple agents
does not meet the strict profile.

Use one of:

- a user-assigned Managed Identity per agent instance;
- an Entra workload identity/federated credential per agent instance; or
- a service principal per agent instance when managed/workload identity is not
  available.

Production resolution selects the expected workload credential explicitly. An
unconstrained `DefaultAzureCredential` chain that may fall through to a
developer login or a different host identity is not sufficient for strict
proof.

Assign the narrowest practical Key Vault data-plane scope: individual secret,
dedicated vault, or another resource boundary that prevents the agent identity
from reading peer credentials. Each signing/API secret value is independently
generated. Diagnostic logs must expose the Entra object/client identity used for
each read.

If Azure resource topology makes per-secret RBAC unmanageable, use a dedicated
vault per agent/trust boundary or an authenticated broker. Granting every agent a
vault-wide reader role is not an acceptable shortcut.

### 6.3 Windows Credential Manager / DPAPI

Credential target names are lookup keys, not process-level access control.
User-scope DPAPI distinguishes Windows accounts; it does not distinguish two
agents running as the same account. Machine-scope DPAPI is broader still.

The strict Windows profile therefore requires one Windows security principal
per agent instance, normally a dedicated service account or gMSA, with:

- its own user-scoped Credential Manager/DPAPI store;
- independently generated signing and downstream credentials;
- logon-as-service and filesystem rights limited to that workload; and
- Windows audit correlation to that security principal.

If multiple agents share one interactive or service account, Windows Credential
Manager is development/single-trust-boundary only and doctor reports personal
credential isolation unavailable. Use Vault or AKV when distinct Windows
accounts are not operationally viable. Machine-scope secrets are prohibited for
strict per-agent runtime credentials.

### 6.4 Local files and environment variables

Separate filenames or environment-variable names under one OS account do not
prevent peer processes from reading each other's credentials. A strict local
profile requires distinct OS/container identities and filesystem/process
boundaries, or delegates resolution to Vault/AKV.

Literal, `env:`, and ordinary `file:` credentials remain acceptable for tests
and explicitly single-agent development. They cannot qualify multi-agent
credential isolation.

## 7. Target-service credentials

Backend isolation alone is insufficient if every agent retrieves the same
downstream password.

### 7.1 Postgres/regista

Separate authorization from login:

- retain a non-login project role containing schema privileges;
- issue a unique login or short-lived dynamic credential per agent instance;
- grant that login membership in the permitted project role;
- bind connection/application metadata to agent instance and session where
  safe; and
- revoke one login/lease without rotating every project consumer.

Signed regista events remain the authoritative attribution for event authorship,
but the database credential now limits and identifies the connection as an
additional control. A single shared project login becomes a migration/degraded
profile, not the target.

A component service may use its own service credential when agents call an
authenticated API rather than connect directly. The service credential belongs
to that service and is never distributed to agents; agent identity remains
bound at the API and signed-event layer.

### 7.2 APIs, model providers, and SaaS

Prefer a separate service account, OAuth client, token, or scoped API key per
agent instance. Where the system supports token exchange/on-behalf-of, issue a
short-lived token carrying both the agent workload and delegating human context;
do not copy the human's refresh token into the agent.

When the provider offers only one project key, keep it behind a service that
enforces per-agent authorization and quotas. If the key must be injected into
each local agent process, the provider cannot meet the strict profile.

### 7.3 Memory engines

Agents do not select a personal bank by presenting an `agent_id` alongside a
shared provider token. Either:

- each agent uses a unique provider credential authorized only for its banks; or
- agent-notes mediates provider access, authenticates every agent with its
  unique credential, authorizes the requested scopes from that credential, and
  retains the provider service credential itself.

The latter is preferred when a provider lacks fine-grained bank credentials.
The provider audit trail then identifies agent-notes, while agent-notes/regista
receipts identify the originating agent; the evidence boundary is explicit.

### 7.4 Agent Capability Broker

The manifest declares a capability grant, not one team-wide secret binding. The
same capability name resolves against the authenticated agent's credential
binding.

- `direct_unique` and `dynamic_unique` credentials may use the existing
  inject-and-run path.
- `brokered_shared` requires an execute-without-disclosure provider/service.
- `shared_agent_visible` is rejected in strict mode.
- `get` cannot retrieve a brokered shared credential and should be disallowed by
  strict policy for acting credentials.

Receipts record the agent credential, capability, exact qualified command or
operation, target credential ID/lease (not value), policy decision, timing, and
exit/result state.

## 8. Provisioning and configuration

The system/admin identity performs an idempotent enrollment for each agent
instance:

1. create or select the stable agent principal and signed human delegation;
2. allocate a new agent instance;
3. generate/enroll an independent signing key;
4. create the backend authentication entity and narrow policy/RBAC assignment;
5. issue unique database/API/capability credentials or configure a brokered
   mapping;
6. write only non-secret refs and credential IDs into the agent's protected
   runtime configuration;
7. prove the agent can resolve its own credentials and cannot resolve a decoy;
8. record a secret-free provisioning receipt.

Re-running enrollment does not create uncontrolled credentials or overwrite
existing ones. Rotation creates a new credential version/lease, cuts over, and
revokes the old credential without changing peers.

The system-wide `suite.env` retains shared non-secret endpoints and
administrative references. It does not contain a generic runtime token inherited
by all agents. Per-agent wiring is protected from other agent workloads and
binds the expected backend authentication method/subject.

## 9. Doctor, lock, and evidence

Doctor remains read-only and must not fetch secret values merely to compare
them. It consumes backend/issuer metadata and provisioning receipts to report:

- agent principal and instance binding;
- backend authentication method and unique issuer subject;
- credential class and target;
- uniqueness posture (`direct_unique`, `dynamic_unique`, `brokered_shared`, or
  `shared_agent_visible`);
- policy/RBAC scope and wildcard findings;
- expiry/rotation/revocation health;
- target-side or broker attribution coverage;
- unsupported/degraded backend limitations.

`shared_agent_visible`, generic runtime AppRole/Managed Identity, shared Windows
account, vault-wide peer-secret read, duplicate target credential ID, unknown
binding, or missing revocation proof makes strict credential isolation red.

SUITE.lock records contract/profile versions and non-secret credential-binding
digests, never secret paths containing work-domain identifiers or credential
values. Live proof correlates backend audit, broker/service receipt, target
account/lease, signed event, and agent/session evidence.

## 10. Migration from the shared-credential posture

1. Inventory every credential agents can receive, inherit, or cause a child to
   receive: Vault/AKV/Windows auth, signing keys, database roles, model/API keys,
   ACB capabilities, provider tokens, and harness environment.
2. Classify each as unique, dynamic, service-mediated, shared-agent-visible, or
   unknown. Unknown is not unique.
3. Enroll agent principals/instances and issue unique signing/backend
   credentials without revoking the current path.
4. Replace the shared project DB login with per-agent logins/leases or an
   authenticated service boundary.
5. Replace capability secret bindings with per-agent resolution; place
   unavoidable shared-only secrets behind a non-disclosing broker.
6. Run shadow audit correlation and cross-agent denial tests.
7. Cut over one agent at a time and prove independent rotation/revocation.
8. Remove generic runtime tokens, wildcard policies, shared harness env files,
   and shared-agent credential paths.
9. Retain only the distinct administrative provisioning identity and document
   its separate custody.

Migration must not copy the existing shared secret into multiple paths and call
the result separated.

## 11. Work plan

### WI-0.1 — Credential-isolation contract and threat model

Freeze credential classes, uniqueness postures, bindings, exception rules,
backend evidence, and the distinction between agent-visible and service-held
credentials. Threat-model peer read/use, credential copying, generic backend
identity, confused deputy, forged actor fields, cloned hosts, stale delegation,
shared downstream accounts, rotation, and broker compromise.

**AC:** schemas reject `shared_agent_visible` in strict mode, two agents bound to
one credential ID, caller-selected binding, and brokered claims without a
non-disclosure/execution receipt.

### WI-0.2 — Backend capability matrix and live spikes

Prove the exact deployable mechanisms for Vault, AKV, and Windows:

- per-agent Vault entity/AppRole/workload auth and narrow policies;
- per-agent AKV managed/workload identity and narrow RBAC;
- per-agent Windows service account/gMSA and user-scope DPAPI;
- unique/dynamic database credentials and independent revocation.

**AC:** recorded live evidence names product/version, authentication subject,
policy scope, audit fields, rotation/revocation behavior, and limitations.
Marketing documentation or differently named paths are insufficient.

### WI-1.1 — Agent enrollment and credential registry composition

Extend bootstrap/onboarding contracts to create an agent principal and instance,
invoke component/backend provisioners, and collect secret-free binding receipts.
No secret generation or target policy logic is reimplemented in agent-suite.

**AC:** enrolling A and B produces different backend subjects, signing key IDs,
database/API credential IDs, and runtime configurations; re-run is idempotent;
admin credentials never appear in either runtime.

### WI-1.2 — Component and ACB adoption

Components authenticate direct agent access with the unique credential or expose
an authenticated service surface. ACB resolves capability grants per agent and
adds a non-disclosing broker mode before shared-only credentials are allowed.

**AC:** no sanctioned harness inherits a team-wide Vault token, AppRole
SecretID, AKV client credential, DB password, API key, or capability secret.
Child-process inspection and negative fixtures cover env, files, config, and
process arguments.

### WI-2.1 — Doctor, lock, and lifecycle

Add read-only posture reporting, duplicate-binding detection, rotation,
revocation, transfer, host-loss, and decommission flows. Keep administrative and
runtime credentials separate.

**AC:** A rotates/revokes without B outage; a cloned A instance cannot reuse A's
instance credential; expired/revoked/generic/wildcard/shared states are named and
fail strict qualification.

### WI-2.2 — Multi-agent adversarial proof

Provision two humans and at least two agents in a shared project with decoy
credentials and equivalent capability grants.

**AC:**

- A and B receive different credential IDs and values generated independently.
- A cannot authenticate with, resolve, use, enumerate, rotate, or revoke B's
  credentials; B cannot do the same to A.
- Each backend audit read identifies A or B's unique workload subject.
- Each direct target log identifies a unique account/token/lease, or the broker
  receipt explicitly terminates downstream attribution at the broker.
- A shared-only provider secret is absent from both agent processes.
- Revoking A immediately blocks A while B continues the same shared project.
- Prompted `agent_id`, changed secret refs, copied configs, replayed tokens,
  symlink/path tricks, and wrong-host credentials fail for the intended reason.

### WI-3.1 — Cutover and remove generic runtime access

Migrate the dogfood deployment one agent at a time, exercise rollback, then
remove generic suite runtime AppRoles/tokens, vault-wide agent readers, shared
host identities, project DB logins exposed to agents, and team capability
secrets.

**AC:** a post-cutover inventory finds no `shared_agent_visible` or unknown
runtime credential; administrative wildcard access is separately named,
protected, and never available inside an agent session.

## 12. Release gates

The suite may claim per-agent credential isolation only when:

- every active agent has a unique backend authentication subject and signing
  credential;
- every direct target credential is unique/dynamic, or its service/broker
  boundary is explicit and non-disclosing;
- peer denial, independent rotation, revocation, and host-clone negatives pass
  live for the selected backend;
- generic/wildcard administrative credentials are absent from agent runtimes;
- Windows agents use distinct OS security principals or the deployment reports
  that backend unsupported;
- memory personal-bank authorization derives from the unique credential binding;
- doctor, lock, audit bundle, and decommission evidence agree.

“Per-principal secret paths,” “signed actor fields,” “different environment
variable names,” or “the broker injected it without printing it” do not satisfy
this gate when the underlying runtime credential is shared.

## 13. Non-goals

- Reimplementing Vault, Entra, AKV, DPAPI, OAuth, database, or provider policy
  engines in agent-suite.
- Giving every agent its own secret-backend deployment when narrow identities
  and policies are sufficient.
- Duplicating shared public configuration or immutable data per agent.
- Claiming a broker makes the downstream service aware of the originating agent.
- Treating unique credentials as proof that the resulting action was safe,
  correct, or authorized for its content.
- Allowing operational complexity alone to silently restore team-wide runtime
  credentials.
