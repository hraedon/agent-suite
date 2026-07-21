# Release Manifest

The immutable release-time description of a published agent-suite candidate.

## What the manifest is

The release manifest (`release-manifest.json`) is the **immutable
release-time description** of a published candidate. It records:

- The umbrella tag SHA (the tagged commit in `agent-suite`)
- All six constituent SHAs (from `SUITE.lock`)
- Package versions (from `SUITE.lock`)
- Wheel hashes and source archive hashes (when built)
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
| What it describes | What was published | What the operator's estate looks like right now |
| Mutability | Immutable (attached to a tagged release) | Live state (regenerated on each `agent-suite inventory` run) |
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
build time) are skipped — there's nothing to verify against.

## Schema version

The manifest carries a `schema_version` field (currently `"v1"`).
`deserialize_manifest` rejects manifests with an unsupported schema
version, so consumers can gate on the version before interpreting the
fields. Bump the version when the manifest shape changes in a way that
breaks consumers.

## Wheel hashes: current state and forward path

Today, CI does not build wheels — the manifest's `wheel_sha256` and
`source_archive_sha256` fields are empty strings for every constituent.
This is **not** a failure: empty strings are an explicit "not provided"
signal, distinct from "failed to compute." The schema is forward-compatible:
when a future work item adds the wheel-build step to CI, the fields will
be populated without a schema change.

An operator verifying a manifest with `release-manifest verify` against a
local wheels directory will see the wheel hashes verified for any
constituent whose `wheel_sha256` is non-empty; constituents with empty
hashes are skipped (there's nothing to verify against).

## See also

- `docs/bootstrap-contract.md` — the lock format and bootstrap contract
- `src/agent_suite/release_manifest.py` — the manifest module (stdlib-only)
- `src/agent_suite/inventory.py` — the candidate inventory module
- `.github/workflows/release.yml` — the CI workflow that builds both artifacts
