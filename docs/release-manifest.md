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

## Cutting a release

The release identity is one fact in three grammars, and CI refuses a tag that
does not agree with all three (`release.yml` → "Verify release identity", which
calls `release_artifacts.check_release_identity`). **In the commit you tag**,
bump all of:

1. `data/release-board.json` → `release` — the declared identity, e.g.
   `"1.0.0-rc.3"`. This is the canonical source; `agent_suite.lock._suite_release()`
   reads it and every other check reads that accessor.
2. `data/support-matrix.json` → `release` — asserted to equal the board by
   `tests/test_support_matrix.py::test_release_board_and_support_matrix_agree`
   (WI-037), so a partial bump reds the suite on any branch.
3. `src/agent_suite/__init__.py` → `__version__` — the PEP 440 form of the same
   identity (`1.0.0-rc.3` → `1.0.0rc3`; use
   `release_artifacts.pep440_release_version`). `pyproject.toml` has no version
   of its own, so this is the only place the wheel version is written.
4. `SUITE.lock` → `[suite].release` — bumped by `agent-suite lock` as usual, and
   asserted to equal the support matrix by the existing matrix test.

Then tag `v<release>` exactly — `v1.0.0-rc.3` for release `1.0.0-rc.3`. Because
the gate compares the tag to the *declared* release, re-running the workflow on
an older tag (`v1.0.0-rc.2`) after the board has moved on will fail by design:
the artifacts it would build are the current tree's, not that tag's. Re-cut from
the tagged commit instead.

`pytest` enforces steps 1–4 locally: `tests/test_packaging.py` asserts
`__version__` against the declared release, so the suite reds until the bump is
complete.

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
could actually reach:

| Rung | What it proves | When available |
|------|----------------|----------------|
| `wheel_hash_chain` | manifest `wheel_sha256` → the wheel's bytes → the `RECORD` *inside* that wheel → the SHA-256 of **every file the wheel shipped** | the release wheel is still on the host (`--wheels-dir` / `--artifact-wheels-dir`) |
| `recorded_archive_hash` | PEP 610 `archive_info.hashes` recorded at install time equals the manifest's `wheel_sha256` | the installer recorded it — pip from a hashed URL does; **uv installing from a local wheel file records `archive_info: {}` and supplies nothing here** |
| `install_record_only` | every installed file matches the digest in the install's own `RECORD` | dist-info is locatable (almost always) |
| `version_only` | the distribution version, and the wheel *filename* PEP 610 recorded, agree with the manifest | always |
| `no_provenance` | **nothing** — the manifest names a component whose runtime provenance could not be read. A gap, counted against `--require-binding`, never silently "not applicable" | — |
| `not_applicable` | the component is absent, or installed editable / from-VCS / from-a-local-directory | — |

`install_record_only` is a real cryptographic check and it catches an edited
module in `site-packages`, but it never counts as a release binding: `RECORD` is
unsigned and lives in the same writable tree it describes, so anyone able to edit
a module can edit its digest. `tests/test_artifact_attestation.py` demonstrates
exactly that — a tamper that rewrites both the file and its `RECORD` row passes
`install_record_only` and fails `wheel_hash_chain`.

### What the strong rung does NOT cover

The chain proves "every file the wheel shipped". It is narrower than "every file
the interpreter executes", and the difference is exploitable, so each gap is
**enumerated** in the report under `unattested` rather than left implicit:

| `unattested.kind` | Why hashing cannot bind it |
|---|---|
| `bytecode_cache` | `__pycache__/*.pyc` is written by pip with an **empty** `RECORD` digest, or created lazily by the interpreter when the installer did not compile (uv's default). CPython loads a cached `.pyc` in preference to its source whenever the cache header's source mtime+size match, *without reading the source* — so a forged `.pyc` executes while the `.py` digest stays pristine. |
| `installer_generated` | Console scripts (`bin/<name>`), `INSTALLER`, `REQUESTED`, `direct_url.json` are written by the installer, not shipped by the wheel, so no manifest hash covers them. |
| `unrecorded_file` | A file present in a package directory that appears in no `RECORD` at all. |
| `blank_digest` | A `RECORD` row with no digest. pip writes these for bytecode; an attacker can blank any row they can already write. |
| `site_customization` | A `*.pth` in `site-packages` that no installed distribution's `RECORD` accounts for. It executes on every interpreter start. Legitimate ones exist (`_virtualenv.pth`, `distutils-precedence.pth` — placed by the venv seeder, not by a wheel), which is why this is a named gap rather than a mismatch. |
| `relocated_data` | A `*.data/` payload relocated at install time; the `RECORD` path does not say where it landed. |
| `wheel_unavailable` | The release wheel is not present, so the chain could not be attempted. Reported only when no other rung supplied a binding. |

Consequently the report distinguishes two verdicts:

- **`ok`** — nothing was provably wrong.
- **`binds_release_identity`** — a binding rung held **and** the tree holds no
  unattested content. A component with a bytecode cache reports
  `rung_binds: true` but `binds_release_identity: false`, because on that tree
  the rung does not answer the question the operator is actually asking.

Two of the gaps are additionally *checked*, not merely named:

- A console script whose import target is not one of the console scripts the
  wheel's (manifest-covered) `entry_points.txt` declares is a **hard mismatch**.
  This catches the realistic attack — repoint `bin/<name>` at attacker code —
  even when the install `RECORD` row has been blanked. It does not prove the
  whole script body, so the script is still reported as `installer_generated`.
- Files present in the distribution's own directories but absent from every
  `RECORD` are reported, which catches a `.pyc` injected where the installer
  wrote none.

### What `--require-artifact-binding` covers, and what it cannot (WI-048)

`--require-artifact-binding` (doctor) / `--require-binding`
(`release-manifest verify --installed`) makes every gap above fatal. It also
fails when nothing attestable was found at all — a host with every component
absent, or every component installed editable, has zero attestable artifacts,
and greening it would certify nothing.

**A normally-installed host cannot pass it, and this section used to imply
otherwise.** It was headed "Bringing a host to a fully bindable state" and gave
three steps, the third of which ("account for every `.pth` … and the generated
console scripts") has no achievable form. The Linux qualification followed all
three and recorded the result:

```
step 1  keep the wheels + --artifact-wheels-dir     done
step 2  PYTHONDONTWRITEBYTECODE=1, cleared every __pycache__
        -> removed 150 bytecode_cache entries, a real improvement
step 3  account for every .pth and console script   NOT ACHIEVABLE
```

Irreducible residue, 18 files across five components:

| Kind | Count | What |
|---|---|---|
| `installer_generated` | 13 | the console scripts themselves (`bin/regista`, `bin/agent-notes`, `bin/cairn`, `bin/dossier`, `bin/agent-suite`, …) plus `INSTALLER` and `direct_url.json` |
| `site_customization` | 5 | `_virtualenv.pth`, one per `uv tool` env |

All five components reached `wheel_hash_chain` with `ok: true`. None reached
`binds_release_identity: true`.

#### Why it is not reachable, rather than merely not reached

**The residue is not removable.** The console scripts *are* how the CLIs are
invoked, and `_virtualenv.pth` is seeded by uv/virtualenv, not by a wheel.
`deployment-guide.md` §3 prescribes `uv tool install`, so the prescribed install
method structurally produces content no manifest hash covers.

**It is not manifest-bindable either.** A console script's bytes are decided at
install time — its shebang is the absolute path of *this* host's interpreter — so
there is no release-determined hash to compare against. The same is true of
`INSTALLER` and `direct_url.json`.

**And an allowlist keyed to hashes recorded on the host is the install receipt
this document already rejected**, under a different name: it would live in the
same writable tree as `RECORD` and be forgeable by the same actor. Accepting it
for this flag after rejecting it for attestation generally would be inconsistent,
and it would weaken the gate rather than satisfy it.

**Finally, the state decays.** After `lxc restart` with services running, **643
`__pycache__` directories** were back, despite `PYTHONDONTWRITEBYTECODE=1` in
`/etc/environment` — systemd units do not read that file. Even if the residue
were eliminable, a gate whose subject reverts on every boot cannot be a
steady-state check. (If you want bytecode suppressed for the processes systemd
starts, the variable belongs in the unit as `Environment=PYTHONDONTWRITEBYTECODE=1`,
not in `/etc/environment`. That covers those processes and nothing else — an
operator's interactive `regista` invocation will still write caches.)

#### So what is the flag for

**A freshly unpacked, never-executed tree** — a build or release-verification
step, or a container image inspected before first run. There, no bytecode exists
yet, and if the artifacts were unpacked rather than installed by uv there are no
console scripts or `.pth` files either. `--require-binding` on
`release-manifest verify --installed` in CI is its intended home.

It is **not** a host health gate, and `doctor --exit-code` does not apply it
unless asked. Routine `doctor --release-manifest` requires none of this: a
runtime-generated `.pyc` on a correct host is not evidence of compromise, so the
default reports the gap and keeps `ok` true. What it will never do is report
`binds_release_identity: true` for such a host — that flag went from vacuously
passing to honestly failing, and the honest failure is the correct outcome.

#### The achievable target for a running host

**`wheel_hash_chain` with `ok: true`, and the `unattested` residue enumerated and
reviewed.** That is what Lane C recorded and what a qualification should assert:

```sh
agent-suite doctor --exit-code --profile B \
  --release-manifest /opt/suite-artifacts/release-manifest.json \
  --artifact-wheels-dir /opt/suite-artifacts/wheels
# exit=0   artifact attestation: ok - verified at 'wheel_hash_chain';
#          no release-identity binding
```

Then read `unattested` and satisfy yourself that every entry is one of the kinds
above. The two checked gaps do real work here: a console script pointing at an
import target the wheel's `entry_points.txt` never declared is a **hard
mismatch**, not residue, so the realistic attack on the largest residue class is
caught even though the script body is not hashed.

What that leaves uncovered, stated plainly: the *bodies* of 13 installer-generated
files and 5 `.pth` files per host, and any `__pycache__` written since the last
sweep. Closing it needs a mechanism this ladder does not have — a signed install
receipt from a party the host cannot impersonate, or immutable delivery (a
read-only image whose digest is the artifact) — and both are outside a hash
comparison against `RECORD`.

An **install receipt** written at deploy time by the host itself was considered
and rejected: same writable tree as `RECORD`, same forging actor, ceremony without
strength.

## See also

- `docs/bootstrap-contract.md` — the lock format, the bootstrap contract, and
  `doctor` §3.1 (`--profile` scoping) / §3.2 (`--release-manifest`)
- `src/agent_suite/release_manifest.py` — the manifest module (stdlib-only)
- `src/agent_suite/artifact_attestation.py` — the installed-artifact attestation
  ladder, and the module docstring explaining what the strong rung does and does
  not cover
- `src/agent_suite/runtime_provenance.py` — `read_runtime_provenance_with_umbrella`,
  the probe that makes the umbrella entry checkable on a host
- `src/agent_suite/inventory.py` — the candidate inventory module
- `.github/workflows/release.yml` — the CI workflow that builds both artifacts
