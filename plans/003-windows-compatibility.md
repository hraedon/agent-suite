# Plan 003 — Windows compatibility (Claude Code on Windows)

**Status:** In Progress (WI-0 posture confirmed + recorded in bootstrap-contract.md §7 and
install-windows.md); WI-5.1 ✅ for agent-suite (windows-latest CI job added).
Phases 1–4 (component fixes) and WI-5.2 (real-Windows e2e) remain — they live in
the component repos. Phase 2 (DPAPI-custody) interlocks with regista Plan 029
Phase 2: land the custody helper once in regista and have both consume it.
**Author:** Claude (Opus 4.8)
**Strategic role:** The suite's deployment target includes Windows (blueprint
decision 1: Linux + Docker + **Windows Service**), and the operators will run
**Claude Code on Windows** — not guaranteed to be Linux, WSL acceptable as a gate.
Today the suite *mostly* runs on Windows by luck of Python's portability, but has
two classes of real defect: **hard crashes** (`os.O_NOFOLLOW` on native Windows)
and **silent security degradation** (POSIX `0o600`/`chmod` protects nothing on
Windows, leaving private keys and signing keys readable). Neither is caught by CI —
no suite repo has a Windows job. This plan makes Windows a **first-class, proven**
substrate, not an assumed one.

## Ground truth at time of writing (audited across all 7 repos)

**Already Windows-aware — do not regress:**
- cairn's Claude-hook command special-cases win32: `_python_command()` returns
  `python` vs `python3`, invoked as `python -m cairn._claude_hook <action>`
  (`agent-provenance/src/cairn/_install.py:23-33,206`). Runs under a native Windows
  shell.
- regista ships the Windows **DPAPI** secret backend (`windows:` refs,
  `protect_windows_secret`, `regista/_secrets.py:220-430`).
- Skills install to `Path.home()/".claude"/"skills"` — correct on Windows.
- No raw `fcntl` in any suite repo (the one hit, gpo-lens, is not a suite component
  and already has an `msvcrt` branch).

**Hard crashes on native Windows:**
- `os.O_NOFOLLOW` does not exist on Windows → `AttributeError` at call time. Used in
  dossier's key custody and config load: `dossier/src/dossier/keys.py:241,281` and
  `dossier/src/dossier/config.py:86`. These are core paths.

**Silent security degradation on native Windows:**
- `os.chmod(path, 0o600)` / `mkdir(mode=0o700)` do not raise but do not protect on
  Windows (no ACL, no encryption). Spans `dossier/keys.py` + `dossier/secrets.py`,
  `agent-notes/core/secrets.py` + `core/envelope.py`, `cairn/_claude_hook.py` +
  `_bridge.py` + `_doctor.py`, `regista/_provision.py:334`. Private keys and
  `signing.key` land world-readable.

**Pervasive but non-fatal:**
- Config/state dirs hardcode XDG (`~/.config`, `~/.local/state`) with literal
  fallbacks: acb (`model.py`, `cred_vault.py`), agent-notes (`core/config.py`,
  `core/envelope.py`, `core/outbox.py`). These resolve to valid but non-idiomatic
  Windows paths. `platformdirs` is a dependency nowhere.

**Unproven:**
- No `windows-latest` CI job in any suite repo. "Windows works" is currently an
  assertion, and the portfolio's own history (gpo-lens/cert-watch real-Windows runs)
  shows CI hides Windows integration bugs.

## WI-0 — Substrate posture decision (owner-gated, do first)

**Recommended posture: native Windows core; Docker for services; WSL as a supported
fallback, not the gate.** Record it in `docs/bootstrap-contract.md`.

The decision is *not* about where services run — Postgres and any long-running
regista process are containerized on every OS (blueprint decision 1). It is about
the **execution context of the in-harness pieces**: cairn's attestation hook fires
on *every* tool call, plus the agent-notes/cred-* skills. Those run inside Claude
Code's own process context, not in a container — so "Docker for everything" would
mean a `docker exec` per intercepted tool call for the compliance keystone, which is
worse than making that Python natively correct. The coherent split is **Docker for
services + native Python for the harness layer**; WSL only becomes "necessary" if the
native Python fixes (Phases 1–3) are declined.

- **Recommended — native-Windows Python core + WSL/Git-Bash for bash dev-glue only.**
  The library/CLI/harness runtime is natively-Windows-correct (Phases 1–4); the
  *only* things allowed to require WSL or Git-Bash are the bash **dev** installers
  (`install-git-hooks.sh`). Rationale: (a) the regulated/AD use case wants the
  attestation to run in the same security context as the user's real Windows/AD
  identity, using the native **DPAPI/Cred-Mgr** store the team already built —
  WSL puts a Linux VM between the audited tool and the Windows security context and
  cannot reach DPAPI; (b) the onboarding audience is non-dev colleagues, for whom
  "run Claude Code on Windows" is a far lower barrier than "stand up WSL2 first";
  (c) the fix set is bounded and already proven on the lab (gpo-lens/cert-watch/
  acme-adcs-ra all run native Windows).
- **Alternative — WSL-gated.** Claude Code runs inside WSL2; the suite runs as Linux
  unchanged. Near-zero code work, **but forfeits the Windows-native DPAPI/Cred-Mgr
  backend** (unreachable from a WSL kernel) — secrets must then be Vault/AKV
  (network-reachable) — and imposes the WSL setup tax on every operator. If chosen,
  Phases 1–4 shrink to "correctness insurance" and Phase 5 targets WSL, not native.

**Linchpin — CONFIRMED 2026-07-06 (OPERATOR):** Claude Code runs natively on Windows
without WSL. The recommended posture is therefore settled, not pending.

**Sandboxing caveat (record in the operator runbook, agent-suite Plan 001):** on
native Windows, Claude Code's harness-level sandboxing is **not available** — the
agent runs with the operator's full Windows access. This is an accepted tradeoff:
the isolation boundary is the **VM/host**, which is the sandbox the deployment cares
about anyway. Operational consequence: **run Claude Code on Windows inside a
dedicated VM**, never on a workstation with ambient access to anything the agent
shouldn't reach. The suite's job here is unaffected — cairn *records* what the agent
did; it does not *constrain* it — but the runbook must state the VM-is-the-sandbox
requirement explicitly so no operator runs it unsandboxed on a fat host.

The rest of this plan is written for the recommended posture; WSL-gated prunes
Phases 1–3 to optional.

## Phase 1 — Eliminate the hard crashes

### WI-1.1 — Cross-platform symlink-reject open
- Replace bare `os.O_NOFOLLOW` with a helper that ORs it in **only where the
  attribute exists** (`getattr(os, "O_NOFOLLOW", 0)`), and on Windows achieves the
  symlink-redirection guard another way (Windows `os.open` does not traverse
  reparse points the same way; combine with an `os.path.islink`/`Path.is_symlink`
  pre-check, or `FILE_FLAG_OPEN_REPARSE_POINT` semantics). Fix all four sites in
  dossier (`keys.py:241,281`, `config.py:86`).
- **AC:** dossier key custody and config load import and run on native Windows; the
  symlink-attack test still passes on Linux and has a Windows equivalent.

## Phase 2 — Real key-file protection on Windows (ties to regista Plan 029)

### WI-2.1 — A cross-platform "restrict to owner" primitive in regista
- One shared helper: on POSIX, `chmod 0o600/0o700`; on Windows, set an owner-only
  **ACL** (via `icacls` or pywin32) — or, preferably, route private-key custody
  through the **DPAPI `windows:` backend** so the key is encrypted at rest and file
  perms are not the security boundary. This is the natural convergence point with
  **regista Plan 029** (backend-aware custody): on Windows the configured backend
  *is* DPAPI, and enrollment stores a `windows:` blob instead of a chmod'd `.key`.
- Consumers (dossier, agent-notes, cairn) call the shared helper instead of raw
  `chmod`.
- **AC:** on Windows, a freshly enrolled/created private key is either DPAPI-encrypted
  or ACL'd to the owner; a `doctor` check flags a key file that is neither.

## Phase 3 — Config/state directory portability

### WI-3.1 — Idiomatic per-platform dirs, env vocabulary preserved
- Adopt `platformdirs` (or a tiny shared resolver) for the *default* config/state
  location: `%APPDATA%`/`%LOCALAPPDATA%` on Windows, XDG on Linux. **The canonical
  suite env vars remain the primary source** (`$AGENT_SUITE_CONFIG`,
  `REGISTA_*`, `<TOOL>_*`) — platform dirs only replace the hardcoded `~/.config`
  *default*. Fix acb (`model.py`, `cred_vault.py`) and agent-notes (`core/config.py`,
  `core/envelope.py`, `core/outbox.py`).
- **AC:** on Windows with no env overrides, config/state resolve under `%APPDATA%`;
  the existing env-var and `$AGENT_SUITE_CONFIG` layering is unchanged on both OSes.

## Phase 4 — Dev + harness glue

### WI-4.1 — Cross-platform git-hook installer
- Pair each `scripts/install-git-hooks.sh` with a `.ps1` companion, or replace both
  with a Python installer invoked via `core.hooksPath` shim. Dev-time only; keep it
  simple. (Under WSL-gated posture this WI is unnecessary.)

### WI-4.2 — Verify harness + skill install on Windows
- Confirm agent-notes `install-harness`, acb adapter wiring, and cairn hook install
  write correct paths and commands on Windows (they use `Path` + the win32-aware
  cairn command, so this is a validation WI, not a rewrite). Confirm the emitted
  hook/skill JSON drives correctly under Claude Code on Windows.

## Phase 5 — Prove it (the part CI can't fake)

### WI-5.1 — `windows-latest` CI job per suite repo ✅ (agent-suite)
- Add a Windows job to each repo's CI: install, import, unit tests, and specifically
  the perm/path/custody logic. This catches the import-time and attribute crashes
  cheaply and permanently.
- **agent-suite:** windows-latest job added (install, architecture test, ruff,
  mypy, pytest). Integration tests skip cleanly (no Docker/Postgres on the runner).
  Other suite repos need their own Windows jobs — track per-repo.

### WI-5.2 — Real-Windows end-to-end on the lab
- Validate on the Win Server 2025 box (`mvmcitest01`, Py 3.14 — see
  [[reference-cert-watch-windows-test-vm]]): **Claude Code on Windows** drives one
  work-item through a face → cairn attestation hook fires → signed event lands in
  regista, with a **DPAPI-custodied** principal key. This is the integration proof;
  per portfolio precedent (gpo-lens/cert-watch), CI will not surface these bugs.

## Notes & non-goals

- **Sequencing:** WI-0 first (posture). Phase 1 (crashes) is the floor — do it
  regardless of posture. Phase 2 interlocks with **regista Plan 029** — ideally land
  the DPAPI-custody path once and have Windows consume it. Phases 3–4 are polish/
  cohesion. Phase 5 is the gate on calling Windows "supported."
- **Not in scope:** Windows Service packaging/installer (blueprint's Windows Service
  target is a separate operator-deliverable), MSI/Chocolatey distribution.
- **Dependency note:** WI-5.2 needs the lab box + a reachable Postgres and the chosen
  secret backend — the same §4 externals the pilot needs.
