"""`agent-suite install-services` — the artifact-only service install (WI-044).

The Plan 020 Linux qualification found that no wheel shipped a systemd unit, that
no `dossier.service` existed anywhere, and that `docs/install-linux.md` §7 told
operators to `systemctl enable --now dossier` anyway. Nothing in the suite could
bring up the services the docs promised, and there was no test that asked.

These tests assert the properties that gap violated: the set of components with
OS services is read from one place and matches reality, the umbrella delegates to
each component's own installer, and it reports success only when systemd says the
unit is running — a component CLI's own claim is not evidence.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_suite.components import COMPONENTS, Tier, component_by_ident
from agent_suite.services import (
    ServiceStatus,
    format_services_report,
    install_component_services,
    service_components,
)


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    def __init__(self, outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]]) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                return out
        return _completed()


def _installer_payload(
    unit: str, *, status: str = "installed", verified: list[str] | None = None
) -> str:
    return json.dumps({
        "unit": unit,
        "status": status,
        "detail": f"{status} and verified",
        "exec_start": f"/usr/local/bin/{unit} serve --host 127.0.0.1 --port 8000",
        "files_written": [f"/etc/systemd/system/{unit}.service"],
        "verified": verified
        if verified is not None
        else ["exec_start_runnable", "systemd_execstart_runnable", "service_active"],
    })


def _which_all(executable: str) -> str | None:
    return f"/usr/local/bin/{executable}"


def _no_sleep(seconds: float) -> None:
    """Verification must be testable without spending its settle window."""
    return None


def _happy_runner(*, state: str = "active") -> StubRunner:
    outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
    for comp in service_components():
        outputs[(f"/usr/local/bin/{comp.doctor_cmd[0]}", "install-service")] = _completed(
            stdout=_installer_payload(comp.service_unit)
        )
        outputs[("systemctl", "is-active", comp.service_unit)] = _completed(
            stdout=state, returncode=0 if state == "active" else 3
        )
    return StubRunner(outputs)


# ---------------------------------------------------------------------------
# Which components have services, and does the declaration match reality
# ---------------------------------------------------------------------------


def test_dossier_is_the_tier_0_1_service_component() -> None:
    """dossier runs as an OS service; install-linux.md §7 promises exactly that."""
    idents = [c.ident for c in service_components(max_tier=Tier.FACE)]
    assert "dossier" in idents


def test_agent_notes_declares_no_service_unit() -> None:
    """WI-044: `agent-notes.service` has never existed in any repo or wheel.

    agent-notes is a CLI over the projection database, not a daemon; its
    bridge/requeue/trigger-loop units are optional harness-side helpers. A
    declared unit that does not exist made `upgrade` attempt a restart that could
    only fail, and made install-linux.md §7 look supported.
    """
    assert component_by_ident("agent-notes").service_unit == ""


def test_service_components_is_derived_not_hardcoded() -> None:
    """The list comes from Component.service_unit, in one place."""
    assert set(service_components(COMPONENTS)) == {
        c for c in COMPONENTS if c.service_unit
    }


def test_tier_limit_excludes_plumbing() -> None:
    core = service_components(max_tier=Tier.FACE)
    assert all(c.tier is not Tier.PLUMBING for c in core)


# ---------------------------------------------------------------------------
# Delegation to the component's own installer
# ---------------------------------------------------------------------------


def test_install_delegates_to_each_component_install_service() -> None:
    runner = _happy_runner()
    report = install_component_services(sleeper=_no_sleep, runner=runner, which=_which_all)
    assert report.ok, [r.detail for r in report.results]
    for comp in service_components():
        assert any(
            call[0].endswith(comp.doctor_cmd[0]) and call[1] == "install-service"
            for call in runner.calls
        ), f"no install-service invocation for {comp.ident}"


def test_install_passes_bin_dir_through_to_the_component(tmp_path: Path) -> None:
    """WI-045: the component needs to know where the CLIs are to build ExecStart."""
    runner = _happy_runner()
    install_component_services(
        sleeper=_no_sleep, runner=runner, which=_which_all, bin_dir=tmp_path / "bin"
    )
    installer = next(c for c in runner.calls if "install-service" in c)
    assert "--bin-dir" in installer
    assert installer[installer.index("--bin-dir") + 1] == str(tmp_path / "bin")


def test_bin_dir_steers_discovery_not_just_the_forwarded_flag(tmp_path: Path) -> None:
    """`--bin-dir` must let the umbrella *find* the CLI, not only tell it apart.

    Measured on the qualification host: under `sudo`, PATH is replaced by
    `secure_path`, so a component installed under `~/.local/bin` is invisible to
    `shutil.which` — and `--bin-dir` exists precisely because the default lookup
    cannot see it. Forwarding the flag while still discovering through PATH left
    `install-services --bin-dir ...` reporting `cli_missing`.

    A tmp bin dir is user-owned, so the WI-038 scope gate (applied below in
    test_install_refuses_a_non_system_bin_dir) would refuse it; this test
    injects a probe to mark it system-scoped and focus on discovery alone.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
    for comp in service_components():
        exe = bindir / comp.doctor_cmd[0]
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
        outputs[(str(exe), "install-service")] = _completed(
            stdout=_installer_payload(comp.service_unit)
        )
        outputs[("systemctl", "is-active", comp.service_unit)] = _completed(stdout="active")
    runner = StubRunner(outputs)

    report = install_component_services(
        runner=runner,
        which=lambda name: None,  # a sanitized sudo PATH sees nothing
        bin_dir=bindir,
        sleeper=_no_sleep,
        system_scope_probe=lambda d: d.resolve() == bindir.resolve(),
    )
    assert report.ok, [r.detail for r in report.results]
    for comp in service_components():
        assert any(call[0] == str(bindir / comp.doctor_cmd[0]) for call in runner.calls)


def test_install_refuses_a_non_system_bin_dir(tmp_path: Path) -> None:
    """DEFECT 1: install-services applies the SAME scope gate as `schedule
    install` (WI-038) — a CLI resolved from a user-writable bin dir is refused
    rather than anchoring a root-run service on it. tmp_path is owned by the
    test user, so the default ownership probe refuses it without any allowlist."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for comp in service_components():
        exe = bindir / comp.doctor_cmd[0]
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
    report = install_component_services(
        runner=_happy_runner(),
        which=lambda name: str(bindir / name),  # resolves into the user-owned dir
        bin_dir=bindir,
        sleeper=_no_sleep,
    )
    assert not report.ok
    assert all(r.status is ServiceStatus.CLI_NON_SYSTEM_SCOPE for r in report.results)
    assert all("non-system bin directory" in r.detail for r in report.results)


def test_install_accepts_a_system_scoped_bin_dir() -> None:
    """DEFECT 1: a CLI resolved from a system bin dir (/usr/local/bin, on the
    trusted allowlist) is accepted — install-services and schedule install agree
    on the same directory."""
    report = install_component_services(
        sleeper=_no_sleep, runner=_happy_runner(), which=_which_all
    )
    assert report.ok, [r.detail for r in report.results]
    assert all(r.status is ServiceStatus.INSTALLED for r in report.results)


def test_install_reports_cli_missing_rather_than_a_traceback() -> None:
    report = install_component_services(
        sleeper=_no_sleep, runner=_happy_runner(), which=lambda name: None
    )
    assert all(r.status is ServiceStatus.CLI_MISSING for r in report.results)
    assert not report.ok
    assert all("not on PATH" in r.detail for r in report.results)


def test_install_reports_unsupported_when_the_cli_has_no_install_service() -> None:
    """argparse exits 2 for an unknown subcommand — a component predating the
    contract must be named as such, because the operator's next action differs."""
    outputs = {
        (f"/usr/local/bin/{c.doctor_cmd[0]}", "install-service"): _completed(
            returncode=2, stderr="invalid choice: 'install-service'"
        )
        for c in service_components()
    }
    report = install_component_services(
        sleeper=_no_sleep, runner=StubRunner(outputs), which=_which_all
    )
    assert all(r.status is ServiceStatus.UNSUPPORTED for r in report.results)
    assert not report.ok
    assert all("no `install-service` command" in r.detail for r in report.results)


def test_install_surfaces_the_component_failure_detail() -> None:
    outputs = {
        (f"/usr/local/bin/{c.doctor_cmd[0]}", "install-service"): _completed(
            returncode=1,
            stdout=json.dumps({
                "unit": c.service_unit,
                "status": "failed",
                "detail": "cannot resolve 'dossier' to an absolute path — 203/EXEC",
                "verified": [],
            }),
        )
        for c in service_components()
    }
    report = install_component_services(
        sleeper=_no_sleep, runner=StubRunner(outputs), which=_which_all
    )
    assert all(r.status is ServiceStatus.FAILED for r in report.results)
    assert all("203/EXEC" in r.detail for r in report.results)


# ---------------------------------------------------------------------------
# Verification, not observation
# ---------------------------------------------------------------------------


def test_install_fails_when_the_unit_is_not_active_despite_a_success_report() -> None:
    """The component said it installed the unit. systemd says it is not running.

    This is the standing review question applied: a component's own claim is an
    observation, `systemctl is-active` is the verification. The suite must not
    report a green install over a dead face.
    """
    report = install_component_services(
        sleeper=_no_sleep, runner=_happy_runner(state="failed"), which=_which_all
    )
    assert all(r.status is ServiceStatus.FAILED for r in report.results)
    assert not report.ok
    assert all("reported success but" in r.detail for r in report.results)
    assert all("not active" in r.detail for r in report.results)


def test_installed_results_carry_the_checks_that_passed() -> None:
    report = install_component_services(sleeper=_no_sleep, runner=_happy_runner(), which=_which_all)
    for result in report.results:
        assert result.status is ServiceStatus.INSTALLED
        assert "service_active_after_settle" in result.verified
        assert result.to_dict()["verified"] == result.verified


def test_the_component_claim_is_not_recorded_as_our_own_verification() -> None:
    """A component's `verified` list is its claim, kept in its own field.

    If the umbrella merged the two, a component that reports
    `verified: [service_active]` without checking anything would make the suite's
    evidence field say the service is up. That is laundering an observation into a
    verification — the exact pattern Lane J is auditing.
    """
    outputs = {
        (f"/usr/local/bin/{c.doctor_cmd[0]}", "install-service"): _completed(
            stdout=_installer_payload(c.service_unit, verified=["service_active"])
        )
        for c in service_components()
    } | {
        ("systemctl", "is-active", c.service_unit): _completed(stdout="failed", returncode=3)
        for c in service_components()
    }
    report = install_component_services(
        sleeper=_no_sleep, runner=StubRunner(outputs), which=_which_all
    )
    assert not report.ok
    for result in report.results:
        assert result.component_verified == ["service_active"]
        assert result.verified == []
        assert "not active" in result.detail


class FlappingRunner(StubRunner):
    """`systemctl is-active` answers differently on successive reads."""

    def __init__(
        self, outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]],
        *, states: list[str],
    ) -> None:
        super().__init__(outputs)
        self._states = list(states)

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("systemctl", "is-active"):
            self.calls.append(cmd)
            state = self._states.pop(0) if self._states else "active"
            return _completed(stdout=state, returncode=0 if state == "active" else 3)
        return super().__call__(cmd)


def test_install_fails_when_the_service_starts_then_dies() -> None:
    """One `is-active` read observes that it started, not that it is up.

    A `Type=exec` service reports `active` as soon as its executable starts.
    Measured on the qualification host: installing dossier with an unassignable
    bind address reported `active` and exit 0 while the process was already on its
    way to flapping. The second read, after a settle, is the verification.
    """
    outputs = {
        (f"/usr/local/bin/{c.doctor_cmd[0]}", "install-service"): _completed(
            stdout=_installer_payload(c.service_unit)
        )
        for c in service_components()
    }
    report = install_component_services(
        runner=FlappingRunner(outputs, states=["active", "activating"]),
        which=_which_all,
        sleeper=_no_sleep,
    )
    assert not report.ok
    assert all("came up and then went activating" in r.detail for r in report.results)
    assert all(r.verified == [] for r in report.results)


def test_install_fails_when_the_service_is_flapping() -> None:
    """Still `active` on the second read, but NRestarts says it has bounced."""
    outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
    for c in service_components():
        outputs[(f"/usr/local/bin/{c.doctor_cmd[0]}", "install-service")] = _completed(
            stdout=_installer_payload(c.service_unit)
        )
        outputs[("systemctl", "is-active", c.service_unit)] = _completed(stdout="active")
        outputs[("systemctl", "show", c.service_unit, "--property=NRestarts")] = _completed(
            stdout="3"
        )
    report = install_component_services(
        runner=StubRunner(outputs), which=_which_all, sleeper=_no_sleep
    )
    assert not report.ok
    assert all("flapping" in r.detail for r in report.results)


def test_install_actually_waits_before_believing_the_service_is_up() -> None:
    """The settle is real elapsed time, not a comment."""
    waited: list[float] = []
    install_component_services(
        runner=_happy_runner(), which=_which_all, settle_seconds=1.5, sleeper=waited.append
    )
    assert waited == [1.5] * len(service_components())


def test_dry_run_acts_on_nothing_and_does_not_claim_a_running_service() -> None:
    runner = _happy_runner()
    report = install_component_services(
        sleeper=_no_sleep, runner=runner, which=_which_all, dry_run=True
    )
    assert report.ok
    installer = next(c for c in runner.calls if "install-service" in c)
    assert "--dry-run" in installer
    # No is-active probe: nothing was started, so there is nothing to verify.
    assert not any(c[:2] == ("systemctl", "is-active") for c in runner.calls)
    assert all("service_active_after_settle" not in r.verified for r in report.results)


def test_uninstall_passes_the_flag_and_reports_removed() -> None:
    runner = _happy_runner()
    report = install_component_services(
        sleeper=_no_sleep, runner=runner, which=_which_all, uninstall=True
    )
    assert report.ok
    installer = next(c for c in runner.calls if "install-service" in c)
    assert "--uninstall" in installer
    assert all(r.status is ServiceStatus.REMOVED for r in report.results)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_install_services_json_and_exit_code(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from agent_suite.cli import main

    monkeypatch.setattr("agent_suite.services._default_which", _which_all)
    monkeypatch.setattr("agent_suite.services._default_runner", _happy_runner())
    assert main(["install-services", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["results"]


def test_cli_install_services_exits_nonzero_on_a_dead_unit(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from agent_suite.cli import main

    monkeypatch.setattr("agent_suite.services._default_which", _which_all)
    monkeypatch.setattr("agent_suite.services._default_runner", _happy_runner(state="failed"))
    assert main(["install-services"]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_format_report_names_the_units_and_the_verdict() -> None:
    report = install_component_services(sleeper=_no_sleep, runner=_happy_runner(), which=_which_all)
    text = format_services_report(report, "install-services")
    assert "dossier" in text
    assert "install-services: OK" in text
