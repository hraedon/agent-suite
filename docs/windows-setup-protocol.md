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
