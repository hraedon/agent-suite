# The bootstrap contract — design spine

This document is to agent-suite what the posture catalogue is to a lens tool: the
contract that dictates what the three commands (`bootstrap`, `doctor`, `lock`) do,
in what order, with what guarantees. It is deliberately written before the code —
the ordering and idempotency rules are the intellectual core, and getting them
wrong deploys a broken suite onto a real machine.

Everything here composes the components through their own documented CLIs
(regista Plan 025/026, dossier 013/014, agent-notes 017, cairn 008, acb 005, wake
004). agent-suite adds *ordering, idempotency, aggregation, and docs* — no
component logic. The shared `install-harness` interface each component implements
is defined in [`install-harness-contract.md`](install-harness-contract.md); the
key-custody security model is in
[`key-custody-threat-model.md`](key-custody-threat-model.md).

## 1. The install order (what `bootstrap` runs)

A fixed sequence; each step is idempotent (re-running a completed step changes
nothing) and gated on the prior step's success. `--dry-run` prints the plan and
acts on nothing. A step that would clobber an existing irreversible artifact (a
signing key, a populated schema) **refuses and reports**, never overwrites.

| # | Step | Calls | Idempotency rule | Gate |
|---|------|-------|------------------|------|
| 0 | **Every configured secret ref resolves** + `suite.env` present | `regista secrets --ref` per discovered ref | read-only check | aborts naming the failing ref |
| 1 | Postgres reachable | DSN probe | read-only check | aborts if unreachable |
| 2 | Provision **every configured project's** schema + service role + principal keys | `regista provision`, `regista provision-principal` | skips existing schema/role (on the child's own affirmative report, not on silence); refuses to clobber an existing key | gates all faces |
| 3a | agent-notes' projection schema | `agent-notes-migrate --all`, verified by `agent-notes doctor`'s `schema_up_to_date` | verifies first; migrates only if the check does not pass | needs step 2 |
| 3b | Faces up | `dossier` (container/Windows Service), `agent-notes install-harness <target>` | re-run reinstalls to the same state | needs step 2 |
| 4 | Provenance on | `cairn install-harness <target>` | re-run is a no-op | needs step 2 |
| 5 | Capabilities | `acb install-harness <target>` | re-run is a no-op | optional (Tier 2) |
| 6 | Signaling | `agent-wake` adapter/daemon install | re-run is a no-op | optional (Tier 2) |
| 7 | Per-user onboarding | writes a per-user `suite.env` overlay, runs `install-harness` for that user | re-run updates the overlay | per additional human |

### What "the step succeeded" means (WI-040, WI-041, WI-042, WI-043)

A step reports success only from a fact the child asserted, never from the
absence of a complaint. Concretely:

- **The exit code cannot green a step on its own, and cannot green one at all
  against the body.** `regista provision --json` exits **0** while its JSON body
  carries `{"error": "permission denied to create role", "service_role_created":
  false}`; that is a failed step. Any `{"ok": false, "error": {...}}` envelope
  (`cli-contract.md` §3) or non-empty `error` on a result record fails the step
  whatever the exit code says, and the report names the contract violation so the
  bug is filed against the child.
- **A field the child did not emit is not evidence.** The suite declares which
  result fields it must read to judge each step; a result missing one of them is
  a failure, not a pass.
- **Classification is by stable error code, never by message text.** A
  `provision-principal` refusal is `PRINCIPAL_KEY_ALREADY_EXISTS`. The previous
  implementation substring-matched the child's prose and treated
  "already"/"exists" as *success*, which made regista's wording part of this
  contract and failed toward green.
- **`already_done` requires affirmative evidence** that the work was already
  present (`schema_created: false` with no error, `already_existed: true`), never
  "nothing bad was said". The qualification host reported `already_done` on its
  **first** bootstrap.
- **Step 0 resolves; it does not enumerate providers.** `--list-providers` proves
  a provider class is registered in regista's process — a host whose only
  `vault:` ref was 403 passed that check. Step 0 discovers the refs the resolved
  config actually names (suite env vars carrying a backend scheme, plus per-key
  `secret_ref` entries inside `REGISTA_KEY_PATH`'s `keys.json`) and resolves each
  one. It states in its own output what it did *not* verify: a ref belonging to
  another component is resolved through regista's environment, and that
  component's own venv must also carry the backend client.
- **A principal is one key, registered in every project it acts in.** regista
  refuses to mint a second keypair for a principal that already holds a signable
  one (WI-223), because one shared `keys.json` plus per-project `principal_keys`
  meant the second mint left the first project's chain signed by a key it never
  registered. Step 2 passes `--reuse-existing-key` on that refusal, so
  `suite-service` — which acts in every project on the host — ends up with one
  key registered in each.

**Order rationale:** secrets and the store must exist before anything that signs
or writes; the faces before provenance (provenance attests *their* actions); Tier 2
last because the core is useful without it. The order matches blueprint §2.3.

`bootstrap --harness` accepts the closed suite set `claude | opencode | codex |
all`; the default is `all`. Its stable expansion is Claude, then OpenCode.
Codex is an explicit candidate target until all required component adapters
pass conformance; component-private targets are excluded. The suite expands `all` before
invocation and calls every child positionally as
`<cli> install-harness <concrete-target> [--json]`. JSON is requested from
components that implement the shared result contract and is schema-validated;
non-zero, malformed JSON, `degraded`, `unsupported`, and `failed` all stop the
pipeline. There is currently no suite-tier exception for degraded installs.

The default `all` remains deployable while Codex work is in progress. An
explicit `--harness codex` fails closed at the first unsupported component.
Codex joins `all` atomically only after the full component set passes the shared
contract and integration proof.

## 2. Configuration resolution (multi-user layering)

agent-suite reads and writes `suite.env` but resolves values through regista's
loader (Plan 025 WI-1.1) so precedence is identical everywhere:

```
process env  >  ~/.config/agent-suite/suite.env (per-user)
             >  /etc/agent-suite/suite.env  (or %ProgramData%\agent-suite on Windows, system)
             >  tool default
```

The **system** `suite.env` holds shared facts (DSN host, secret-backend pointers,
the project registry). The **per-user** overlay holds that human's `principal_id`,
default project, and personal harness wiring. `bootstrap` writes the system file
once; `bootstrap --user` writes an overlay per additional human without touching
the shared store (install order step 7).

Canonical vars (regista owns the vocabulary): `REGISTA_DSN`, `REGISTA_KEY_PATH`,
`REGISTA_REQUIRE_SSL`, plus per-consumer `<TOOL>_PROJECT`. Secrets are backend
refs (`vault:` / `akv:` / `wincred:` / `file:`), never literals in the system file.

## 3. The doctor umbrella (what `doctor` aggregates)

`agent-suite doctor [--json]` shells each installed component's `<tool> doctor
--json` (the common shape regista Plan 025 WI-3.1 defines) and folds them into one
report:

```
{ suite_ok: bool,
  components: [ { component, version, ok, regista:{reachable, project, chain_ok},
                  checks:[{name,status,detail}] } … ],
  lock: { matches: bool, drift:[…] },                         # from §4
  post_restore: { ok: bool, projects:[…] } | null }          # from §WI-4.2
```

Rules: a component that isn't installed is `absent` (not a failure — the suite may
not deploy Tier 2); a component that's installed but unreachable is a failure; the
umbrella is read-only and never mutates. A **shared-service** component (dossier,
Plan 004 WI-1.6) is checked by **endpoint** when not installed locally: with an
endpoint configured in suite.env (e.g. `DOSSIER_URL`), the doctor probes
`<url>/healthz` and reports `remote: ok @ <version>`; with the endpoint down, a
legible failure naming the URL; with no endpoint configured, `not configured
(shared service)` — a named state distinct from both `absent` and `failed`.
`--exit-code` gates a monitoring run. When `--verify-restore` is passed,
`post_restore` is populated with the `verify_restore` result (Plan 001 WI-4.2) and
a failed post-restore check makes `suite_ok` false; when `--verify-restore` is not
passed, `post_restore` is `null`. `--verify-restore` requires a DSN (`--restore-dsn`
or `REGISTA_DSN`) — the command errors if neither is provided.

Codex plugin health preserves qualified `name@marketplace` identity. The
release marketplace is checked by default; a dogfood deployment may select its
intentional local source with `--codex-marketplace` or
`AGENT_SUITE_CODEX_MARKETPLACE`. A same-name plugin from any other marketplace
never satisfies the pin.

### 3.1 `--profile` scopes requirement strictness (WI-036)

Without `--profile`, **every** installed-but-broken component reds `suite_ok`,
and only the spine's *absence* reds it.

With `--profile X`, what changes is **requirement strictness**, not failure
tolerance:

- A component in `PROFILE_REQUIREMENTS[X]` that is failed, unreachable,
  **absent**, not-configured, or unreported reds the verdict. Absence counts
  here — the operator declared the profile, so its requirements are the
  contract. This is stricter than the unscoped rule.
- A non-required component's **absence** (`absent` / `not_configured`) does not
  red the verdict, and is named in `profile_scope.out_of_profile_absent`. This
  is what the flag buys: a Profile-B host that does not deploy the C tier is
  green instead of being judged against components nobody asked it to run.
- A non-required component that is **installed and broken** *still* reds the
  verdict, and is named in `profile_scope.out_of_profile_failures`.

That last rule is deliberate and was corrected during review. An earlier
revision excluded out-of-profile failures, which produced a report that
simultaneously said `profile_classification.profile: "C"` and `suite_ok: true`
while three Profile-C components answered `ok:false`. "Not answerable for
plumbing it was never asked to run" describes **absent**, not **failed** — a
component that was probed and answered `ok:false` is running on this box and is
broken, whatever profile the operator asserts. WI-036 already named the remedy:
configure the tier, or uninstall it.

Because no failure is ever excluded, two things follow. The lock check needs no
profile scoping of its own, so `doctor` and `lock --check` cannot disagree about
whether an out-of-profile component matters. And the report cannot contradict
itself: `profile_scope.detected_outranks_asserted` is reported for legibility
(the host looks broader than the asserted profile) but is *informational*,
because nothing is being hidden.

```
profile_scope: { profile, required[], in_profile_failures[],
                 out_of_profile_failures[], out_of_profile_absent[],
                 detected_profile, detected_outranks_asserted }
```

### 3.2 `--release-manifest` attests the installed artifacts (WI-036)

Wheel-installed components carry no VCS revision by construction (PEP 610
records `archive_info`, not `vcs_info`), so lock checking degrades to a
version-only comparison — and a version string is a claim, not evidence. Point
the doctor at the release manifest the host was deployed from:

```sh
agent-suite doctor --exit-code \
  --release-manifest /path/to/release-manifest.json \
  --artifact-wheels-dir /path/to/wheels
```

Both accept an env fallback (`AGENT_SUITE_RELEASE_MANIFEST`,
`AGENT_SUITE_ARTIFACT_WHEELS_DIR`). Any mismatch makes `suite_ok` false.

The report states two separate things, and the difference matters:

- **`ok`** — nothing was provably wrong. A digest disagreement, a missing
  recorded file, a wrong version, or a console script repointed at code the
  release never declared all make this false.
- **`binds_release_identity`** — the running code is cryptographically tied to
  the published release. This is *stricter* than `ok`, and it is false whenever
  the tree contains content no digest covers: bytecode caches, installer-generated
  console scripts, unrecorded files, or a `.pth` no distribution accounts for.
  Every such item is enumerated under `unattested` with its reason.

The strong rung proves "every file the wheel shipped" — **not** "every file the
interpreter executes". See `docs/release-manifest.md` §"Attesting an installed
artifact" for the full ladder, what each rung does and does not cover, and how
to bring a host to a fully bindable state.

`--require-artifact-binding` promotes "no cryptographic binding available" from
an honestly named gap to a failure. It also fails when *nothing* attestable was
found (all components absent, or all installed editable) — a qualification gate
that greened an empty host would certify nothing. Use it in platform
qualification, not routine health.

## 4. The compatibility lock (`SUITE.lock`)

A committed manifest pinning the known-good set:

```toml
[suite]
release = "1.0.0-dev"
regista_library_version = "0.5.1"
regista_schema_version = 43
regista_workflow_version = "2"
regista_envelope_version = 5

[components.regista]
repo = "hraedon/regista"
version = "0.5.1"
revision = "ea434ace9a65bdcadf6161056433b57d7afeca01"

[components.dossier]
repo = "hraedon/dossier"
version = "0.0.1"
revision = "db834d834a7f3291acbe9206fcc6226f0b5f96c6"

[components.agent-notes]
repo = "hraedon/agent-notes"
version = "1.0.0"
revision = "a33e95092342b8d723a72d66275892531907ec64"

[components.agent-provenance]
repo = "hraedon/agent-provenance"
version = "0.1.0"
revision = "3605d67f15b03e0ed2dc2ce12f719729607066af"

[components.agent-capability-broker]
repo = "hraedon/agent-capability-broker"
version = "0.1.0"
revision = "9610aef6c0d223bc33157b200711953700ce747d"

[components.agent-wake]
repo = "hraedon/agent-wake"
version = "0.1.0"
revision = "90d83803e0824be132dfa531c07daa364a753966"
```

`agent-suite lock` regenerates it from the currently-pinned set; `doctor`
compares the installed versions against it and reports drift. A **suite release
is a green `SUITE.lock`** — the pinned set passed the interop test (§5). This is
what makes "deploy the suite" reproducible: you deploy a release, not six
moving `@main`s.

### The `revision` field

The `revision` field on each component pin is **optional**. Older locks omit it;
locks generated in environments where the source checkout is absent (CI from
wheels, production installs) also omit it. When present, it is the full git SHA
(40-char sha-1 or 64-char sha-256 hex) the lock was generated against, and it is
what makes the lock a *reproducible candidate definition* rather than a version
hint: a version can be republished, but a SHA cannot.

`agent-suite lock` refuses to combine an installed version with a different
candidate checkout version. This prevents internally false pins such as a
runtime `0.5.1` paired with the SHA of a `0.5.3` checkout.

**The both-sides-have-SHA gate:** `check_drift` reports `REVISION_MISMATCH` only
when *both* the locked pin and the current state carry a SHA. A version-only lock
cannot detect revision drift by design; a current state where the SHA is
unprobeable (a wheel install with no source checkout) does not false-positive
against a locked revision.

Runtime drift checks inspect the exact interpreter that owns the visible CLI
and its PEP 610 metadata. They never substitute a similarly named checkout
under `/projects`. Clean editable installs and Git direct-URL installs can carry
an attributable revision; ordinary wheels remain version-only. For a shared
remote service, a local client checkout is never used as server provenance.

**Failure mode:** an operator who generates a lock in CI-from-wheels gets a
version-only lock — same-version rebuilds at a different SHA are undetectable.
For candidate releases, generate the lock in an environment with the source
checkouts present (or pin revisions by hand) so the SHA is captured.

## 5. The interop test (what makes a lock "green")

A CI job (using regista's published interop fixture, Plan 025 WI-4.2) stands up an
ephemeral Postgres, `bootstrap`s the Tier 0–1 core at the locked revisions, and
drives **one work-item across both faces to `done`**: an agent (agent-notes) files
and works it; a human (dossier) reads and accepts it; `cairn`/`regista verify`
confirm the mixed human+agent chain verifies with **per-actor signatures** (regista
Plan 026). A lock that can't do this is not a release.

**The per-actor requirement is asserted, not described (WI-052).** The offline
bundle must report `signatures_unverifiable == 0`, with `signature_check` =
`enforced` and every event verified — not merely `verified: true`. The Lane C
qualification passed this lock while producing *"5 event(s), 4 signature(s)
verified, 1 unverifiable (symmetric scheme)"*: the human leg was signed with the
**shared store HMAC key**, which every actor and the server hold, so it is
attributable to nobody. A prose requirement that a green lock can violate is not
a gate, so the assertion lives in code —
`agent_suite.signature_assurance.bundle_verdict`, exercised by
`tests/test_signature_assurance.py` against those exact numbers and asserted by
the face-level interop test.

The replay leg is subject to the same rule: a zero `principal_binding_failures`
counts only when `principal_binding_verified` is true. regista omits the count
when the check did not run, precisely so a consumer cannot read "not checked" as
"none found" (WI-051).

## 6. Honest boundaries

- agent-suite proves the components *interoperate and deploy*; it does **not**
  prove any component correct — that's each component's own test suite.
- The doctor umbrella reports reachability and version match; it is not a security
  audit of the deployment.
- The bootstrap automates the documented order; it does not remove the operator's
  responsibility for the external dependencies (Postgres, secret backend, identity
  source, network/audit approvals — blueprint §4). It checks they're present and
  fails clearly when they're not; it cannot procure them.

## 7. Substrate posture (Plan 003 WI-0)

The suite's deployment target includes **Windows** (blueprint decision 1: Linux +
Docker + Windows Service). The confirmed posture (OPERATOR, 2026-07-06) is:

- **Native Windows Python core** for the library, CLI, and harness layer (cairn's
  attestation hook fires on every tool call inside Claude Code's own process —
  containerising that per-call is worse than making the Python natively correct).
- **Docker for services** — Postgres and any long-running regista process are
  containerised on every OS, including Windows.
- **WSL / Git-Bash** as a supported fallback for bash dev-glue only (the
  `install-git-hooks.sh` scripts), **not** as the gate. Claude Code runs natively
  on Windows without WSL.

**Sandboxing caveat:** on native Windows, Claude Code's harness-level sandboxing
is **not available** — the agent runs with the operator's full Windows access. The
isolation boundary is the **VM/host**. Operators must run Claude Code on Windows
inside a **dedicated VM**, never on a workstation with ambient access to anything
the agent shouldn't reach. The suite's job is unaffected — cairn *records* what
the agent did; it does not *constrain* it — but the runbook
([install-windows.md](install-windows.md)) must state this requirement explicitly.

This posture means the component repos must be natively Windows-correct
(Plan 003 Phases 1–4): no `os.O_NOFOLLOW` crashes, real key-file protection
(DPAPI or ACL, not `chmod 0o600`), and idiomatic config/state directories.
A `windows-latest` CI job per repo (Plan 003 WI-5.1) catches import-time and
attribute crashes cheaply and permanently.
