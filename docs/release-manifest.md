# Release Manifest

The release-time description of an agent-suite release candidate.

## What the manifest is

The release manifest (`release-manifest.json`) is the **release-time
description** of a candidate. Since Gate 2 (release-board WI-2.3) CI builds
wheels from the `SUITE.lock`-pinned checkouts and records their SHA-256, so the
manifest describes an **artifact candidate**, not only a source one. When we say
the manifest is *immutable* we mean the **record** is tamper-evident (a self-SHA
over its content). It records:

- The umbrella tag SHA (the tagged commit in `agent-suite`)
- All six constituent SHAs (from `SUITE.lock`)
- Package versions (from `SUITE.lock`)
- Wheel hashes and source archive hashes (when built)
- The **umbrella artifact** (`agent_suite`'s own wheel) with its own hash and a
  version derived from the release board — schema v2, WI-035
- The regista version quad (library, schema, workflow, envelope)
- The lock identity (SHA-256 of `SUITE.lock`, release, component count)
- A self-SHA-256 (tamper-evidence: any modification to the serialized
  manifest changes the self-SHA, and `deserialize_manifest` rejects a
  manifest whose self-SHA doesn't match its content)

The manifest is **not committed to main**. It is attached to the GitHub
release on tag push (alongside the candidate inventory). The main branch
never carries it — committing it would make it self-stale (committing
changes the umbrella HEAD it just recorded).

## What the manifest is not

The manifest is **not** the candidate inventory (`candidate-inventory.json`).
The two are distinct artifacts with distinct purposes:

| Aspect | Release Manifest | Candidate Inventory |
|--------|-----------------|---------------------|
| What it describes | The candidate that was cut | What the operator's estate looks like right now |
| Mutability | Immutable record (attached to a tagged release) | Live state (regenerated on each `agent-suite inventory` run) |
| Scope | The suite's pinned candidate definition | The operator's installed + checkout state |
| When it's generated | CI on tag push | CI on tag push + locally on demand |
| Contains wheel hashes | Yes | No |
| Contains origin provenance | No | Yes |

## How they bind

An operator who has installed a release candidate can bind their estate
inventory to the published manifest via `Inventory.bind_to_manifest`:

```python
from agent_suite.inventory import collect_inventory
from agent_suite.release_manifest import deserialize_manifest

inv = collect_inventory()
manifest = deserialize_manifest(open("release-manifest.json").read())
binding = inv.bind_to_manifest(manifest)

if binding.fully_bound:
    print(f"Estate matches release {manifest.release_tag}")
else:
    for b in binding.bindings:
        if not b.constituent_present:
            print(f"  {b.ident}: absent from inventory")
        elif not b.pinned_revision_matches:
            print(f"  {b.ident}: revision mismatch")
        elif not b.package_version_matches:
            print(f"  {b.ident}: version mismatch")
```

`fully_bound` is `True` iff every manifest constituent is present in the
inventory AND both the pinned revision and the package version match.
A divergent estate (different SHA, different version, or missing component)
makes `fully_bound` `False` with named mismatches per constituent.

## CLI

### Build

```sh
agent-suite release-manifest build --tag v1.0.0-rc1 --json
```

Builds a manifest from the current `SUITE.lock`. The umbrella tag SHA is
resolved via `git rev-list -n 1 <tag>` (falling back to `git rev-parse
HEAD`, then `""` if both fail). When `--wheels-dir` is provided, wheel
SHA-256 hashes are computed from the files in that directory; otherwise,
`wheel_sha256` and `source_archive_sha256` are empty strings (honest "not
provided").

Exits non-zero if `SUITE.lock` is missing, unreadable, lacks a regista
quad, or has a component without a pinned revision.

### Verify

```sh
agent-suite release-manifest verify release-manifest.json --wheels-dir wheels/
```

Re-reads the manifest, recomputes wheel hashes from the `--wheels-dir`
directory, and asserts they match the recorded values. Exits non-zero
on any mismatch. Constituents with empty `wheel_sha256` (not provided at
build time) are skipped — there's nothing to verify against. The umbrella
artifact (schema v2) is verified on the same terms.

Add `--installed` to attest the artifacts installed on **this host** rather
than wheel files on disk — see "Attesting an installed artifact" below.

## Schema version

The manifest carries a `schema_version` field (currently `"v2"`).
`deserialize_manifest` accepts every version in `SUPPORTED_SCHEMA_VERSIONS`
(`v1`, `v2`) and rejects anything else, so consumers can gate on the version
before interpreting the fields.

`v2` (WI-035) adds one optional field, `umbrella_artifact`. It is **omitted
entirely** from the serialized form when absent, so an already-published `v1`
manifest still round-trips byte-for-byte and its self-SHA still validates —
bumping the schema did not orphan the manifests attached to earlier releases.

## The umbrella artifact (WI-035)

Every release attaches `agent_suite-<version>-py3-none-any.whl` alongside the
six component wheels. It used to ship **unattested**: it was not a manifest
constituent, got no hash, and its version was a static `0.0.1` while releases
were cut as `1.0.0-rc.N` — so successive releases attached identically named
wheels with different contents.

Both halves are now closed:

- **Identity.** `agent_suite.__version__` is the single source of the wheel
  version (`pyproject.toml` reads it via hatchling's dynamic-version hook, and
  carries no literal of its own). `tests/test_packaging.py` asserts it equals
  `pep440_release_version(ReleaseBoard.default().release)`, so cutting
  `1.0.0-rc.3` on the release board fails the test suite until the wheel
  version is bumped with it. `release.yml` additionally asserts the git tag
  equals `v<release board release>` before building anything.
- **Attestation.** The umbrella is a manifest entry with its own
  `wheel_sha256`, verified by `release-manifest verify` and by
  `doctor --release-manifest` like any constituent. It is deliberately *not* a
  lock constituent: `SUITE.lock` pins the six components the umbrella deploys,
  and adding the deployer to its own pinned set would make the lock
  self-referential. `umbrella_artifact` is the right shape for "shipped and
  hashed, but not pinned."

The umbrella's `pinned_revision` is the umbrella tag SHA, which may legitimately
be `""` when the tag could not be resolved at build time — validated only when
non-empty, matching the top-level `umbrella_tag_sha`.

PEP 517 backend versions are pinned exactly (`hatchling==1.31.0`) for
agent-suite's own build: the backend is part of the wheel's byte identity, so an
unpinned backend means two builds of one source can produce two different
manifest hashes. A packaging test enforces that every
`build-system.requires` entry uses `==`.

## Attesting an installed artifact

`release-manifest verify --wheels-dir` answers "are these wheel *files* the ones
the manifest recorded?" On a deployed host the more useful question is "is the
code actually executing here the code the manifest hashed?" — because a
wheel-installed component carries no VCS revision, so lock checking degrades to
version-only and a version string is a claim, not evidence.

```sh
# attest what is installed on THIS host
agent-suite release-manifest verify release-manifest.json --installed \
  --wheels-dir /path/to/release/wheels

# the same check, folded into the health umbrella
agent-suite doctor --release-manifest release-manifest.json \
  --artifact-wheels-dir /path/to/release/wheels --exit-code
```

### What is actually verifiable

Neither uv nor pip retains the wheel file after installing it, and a wheel's
SHA-256 **cannot be reconstructed** from the unpacked tree — a wheel is a ZIP,
and member order, timestamps and compression do not survive unpacking. Any check
claiming to recompute `wheel_sha256` from `site-packages` would be a lie.
`agent_suite/artifact_attestation.py` therefore reports the strongest rung it
could actually reach, and says whether that rung binds the install to the
release identity:

| Rung | What it proves | Binds release identity? | When available |
|------|----------------|-------------------------|----------------|
| `wheel_hash_chain` | manifest `wheel_sha256` → the wheel's bytes → the `RECORD` *inside* that wheel → the SHA-256 of every installed file | **yes** | the release wheel is still on the host (`--wheels-dir` / `--artifact-wheels-dir`) |
| `recorded_archive_hash` | PEP 610 `archive_info.hashes` recorded at install time equals the manifest's `wheel_sha256` | **yes** (but says nothing about post-install edits) | the installer recorded it — pip from a hashed URL does; **uv installing from a local wheel file records `archive_info: {}` and supplies nothing here** |
| `install_record_only` | every installed file matches the digest in the install's own `RECORD` | **no** | dist-info is locatable (almost always) |
| `version_only` | the distribution version, and the wheel *filename* PEP 610 recorded, agree with the manifest | **no** — not cryptographic at all | always |
| `not_applicable` | the component is absent, or installed editable/from-VCS/from-a-local-directory | — | — |

`install_record_only` is a real cryptographic check and it catches an edited
module in `site-packages`, but it is reported as **unbound** on purpose:
`RECORD` is unsigned and lives in the same writable tree it describes, so anyone
able to edit a module can edit its digest. `tests/test_artifact_attestation.py`
demonstrates exactly that — a tamper that rewrites both the file and its
`RECORD` row passes `install_record_only` and fails `wheel_hash_chain`.

An **install receipt** written at deploy time was considered and rejected: it
would live in the same writable tree as `RECORD` and be forgeable by the same
actor, so it would add ceremony without adding strength. The two honest ways to
get a cryptographic binding on a wheel host are (a) keep the release wheels on
the host and point `--artifact-wheels-dir` at them, or (b) install from a hashed
URL so the installer records `archive_info.hashes`.

By default an unbound-but-consistent install is reported, not failed: a host
that no longer has its wheels cannot produce the binding, and the doctor must
not call a correct estate red for an unavoidable evidence gap. Pass
`--require-artifact-binding` (doctor) / `--require-binding`
(`release-manifest verify --installed`) to make the gap fatal — that is the
platform-qualification posture, per Plan 020 Lane C.

## See also

- `docs/bootstrap-contract.md` — the lock format, the bootstrap contract, and
  `doctor` §3.1 (`--profile` scoping) / §3.2 (`--release-manifest`)
- `src/agent_suite/release_manifest.py` — the manifest module (stdlib-only)
- `src/agent_suite/artifact_attestation.py` — the installed-artifact attestation
  ladder, and the module docstring explaining what is and is not verifiable
- `src/agent_suite/inventory.py` — the candidate inventory module
- `.github/workflows/release.yml` — the CI workflow that builds both artifacts
