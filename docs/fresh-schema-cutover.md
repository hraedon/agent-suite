# Fresh-schema v6 cutover

**Status:** Operator runbook, owner decision 2026-08-22

This runbook moves a pre-v6 suite project to the clean v6 epoch. It implements
regista's precedence-bearing `docs/0.6.0/EPOCH-RESET.md` decision: the v6 record
starts at genesis in an empty schema. The legacy event population is frozen and
retained, not migrated or deleted.

The suite layer only orders component commands and verifies their results. It
does not copy component tables itself. If a component lacks a required export,
import, freeze, or catalog operation, stop and add that operation to the owning
component.

## 1. Preconditions

Do not start the write freeze until all of these are true:

- The exact release candidate is pinned in `SUITE.lock` and its interop lanes pass.
- The two independent review verdicts and reproduction evidence required for
  each gate-critical change are durably recorded.
- `regista genesis init` and the `regista.actor_boundary_signing` invariant are
  present in the pinned regista build.
- Every required `agent-suite genesis-gate` check has both pass and deny
  fixtures; no required check is waived or removed.
- Every known-high residual has an explicit ship or defer disposition.
- The backup command and a real scratch restore have both succeeded.
- The operator has named the legacy schema, the new schema, the secret-backend
  references, and the publication repository without putting secret values in
  the runbook or shell history.

## 2. Freeze and measure the legacy store

1. Stop every suite writer and disable scheduled mutating jobs.
2. Make the legacy schema read-only using the approved database control for the
   deployment. Verify a representative write is refused; do not infer the
   freeze from configuration alone.
3. Run regista's strict read-only verification against the frozen schema.
4. Record the canonical final project head hash, event count, and scheme counts.
5. Run `agent-suite backup` to a private operator-selected directory. Record the
   dump digest, byte count, mode, and timestamp outside the repository.
6. Restore that dump into an isolated scratch database and run
   `agent-suite verify-restore`. A successful source-side dump without a
   successful restore is not sufficient evidence.

The legacy schema and final dump remain retained under the deployment's backup
policy. Neither is a source for v6 event writes.

## 3. Create the empty v6 store

1. Provision a distinct empty project schema through regista's documented
   provision command. Never run forward migrations against the legacy schema as
   part of this cutover.
2. Verify the new schema reports the exact pinned schema, workflow, and envelope
   versions and contains no project events.
3. Provision the project, trust, and actor key material through the component
   CLIs and secret resolver. Do not place private key material in PostgreSQL,
   command output, or committed configuration.

If provisioning discovers a checksum mismatch in the legacy schema, leave that
schema frozen. Do not add a checksum exception to make the forbidden production
upgrade path proceed.

## 4. Move operational rows

Use each owning component's documented export/import path to move operational
state such as work items, breadcrumbs, memories, and decisions. Do not copy
regista event rows, signatures, chain projections, or project identity rows.

An operational row that refers to a legacy event must retain all of these
properties:

- the reference is visibly labelled as legacy;
- it identifies the frozen legacy project/schema and immutable event identity;
- it remains resolvable through the read-only legacy store;
- it is never replaced with a newly minted v6 event id or hash.

Stop if the component import surface cannot preserve those properties. Silent
rewriting would turn an operational pointer into a false evidentiary claim.

## 5. Open and publish the new epoch

1. Run `agent-suite invariant-probes --json --exit-code` against the empty v6
   target and retain the report.
2. Run `agent-suite genesis-gate --json --exit-code` against the same target.
   Any missing, duplicate, malformed, unexecuted, or failed required check
   blocks the cutover.
3. Run the pinned `regista genesis init` command once. Verify the signed genesis
   event and project identity before enabling any ordinary writer.
4. Produce and publish the signed estate cutover catalog through regista's
   documented catalog command. Its project entry must bind the frozen legacy
   head hash and event count to the new epoch head; do not hand-author catalog
   JSON.
5. Re-fetch the publication through an independent checkout and verify its
   signatures, catalog fields, and referenced heads.

## 6. Repoint and verify

1. Repoint component configuration to the new schema without changing the
   frozen legacy locator used by legacy-qualified operational references.
2. Start one writer at a time in the documented suite order.
3. Run the suite doctor, interop journey, invariant probes, and a representative
   cross-face work-item lifecycle.
4. Confirm the legacy event count and head hash have not changed.
5. Re-enable schedules only after all checks pass.

Do not merge histories during rollback. If the new epoch must be abandoned,
stop its writers and preserve it for diagnosis. Reopening the legacy event log
requires a new owner decision; this runbook never makes the frozen schema
writable again.
