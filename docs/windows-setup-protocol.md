# Windows Setup protocol foundation

The `agent_suite.windows_setup` module is a non-acting, stdlib-only contract
foundation for Plan 013 WI-0.3. It gives a future Windows CLI and UI the same
closed preflight, plan, action, and receipt states and the same deterministic
plan digest.

The current implementation accepts a caller-supplied, non-secret observation
of the selected release and host, evaluates it, creates a canonical plan, and
emits a dry-run/no-op/blocked receipt. Release or lock identity mismatch fails
closed. It deliberately has no platform probe or executor and is not exposed as
a CLI command. Adding a button or CLI verb must not create an execution path
that bypasses these functions.

Nothing in this foundation claims live Windows qualification. In particular,
it does not install artifacts, request elevation, operate WinSW or Scheduled
Tasks, access DPAPI, test a database or secret provider, apply a bundle, repair
state, or perform restore. Those adapters remain Phase 1–4 work and must be
implemented as allowlisted component/OS operations with Windows evidence.

The versioned wire vocabulary is recorded in
`data/contracts/windows-setup.json`. Protocol changes require fixture, code,
and conformance-test changes together.

## The CLI verb (WI-050)

The read-only evaluation is exposed as **`agent-suite preflight-windows`**. It
checks a **native Windows host** and nothing else. On any other platform it
reports `PLATFORM_NOT_APPLICABLE` and exits 1 without probing anything — it does
not run the probes and print a red report about a platform the operator is not
on, which is what it used to do:

```
$ agent-suite preflight   # on Linux, before WI-050
State: blocked
  windows      unsupported  (required)   native Windows host required
  powershell   unsupported  (required)   PowerShell availability
  dns          unavailable  (required)
exit=1
```

A Linux operator reads that as "my host is broken". `docs/install-linux.md` never
mentions the command, and `agent-suite deploy` uses the word "preflight" for a
different step, so the generic name was the whole defect.

`agent-suite preflight` still works as a **deprecated alias** — anything already
scripting it keeps working — and warns on stderr, naming the replacement. The
exit code is unchanged in both cases: contract §2 requires every path that
reports an error to exit non-zero, so a script that stopped on the old report
keeps stopping.

The `secret_provider_present` row is named for what it establishes. A preflight
runs before any configuration exists, so a provider being *installed* is all it
can check; the row used to be called `secret_provider` with the detail "provider
availability only", stating in the report that it observed presence rather than
verifying anything. Whether a `vault:` ref actually **resolves** is verified by
`agent-suite bootstrap` step 0 (`src/agent_suite/secret_refs.py`, WI-041).
