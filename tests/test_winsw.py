from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from agent_suite.winsw import (
    SUITE_SERVICES,
    ServiceState,
    WinSWServiceSpec,
    generate_winsw_xml,
    install_winsw_service,
    remove_winsw_service,
    format_winsw_report,
)


def _spec() -> WinSWServiceSpec:
    return WinSWServiceSpec(
        name="test-service",
        description="A test service",
        executable="python",
        arguments="-m test_module",
        working_dir="C:/ProgramData/test",
        log_path="C:/ProgramData/test/logs",
        env_vars={"REGISTA_DSN": "placeholder", "TEST_VAR": "value"},
    )


def test_generate_xml_contains_all_fields() -> None:
    xml = generate_winsw_xml(_spec())
    root = ET.fromstring(xml)
    assert root.find("id").text == "test-service"
    assert root.find("name").text == "test-service"
    assert root.find("description").text == "A test service"
    assert root.find("executable").text == "python"
    assert root.find("arguments").text == "-m test_module"
    assert root.find("workingdirectory").text == "C:/ProgramData/test"
    assert root.find("logpath").text == "C:/ProgramData/test/logs"


def test_generate_xml_includes_env_vars() -> None:
    xml = generate_winsw_xml(_spec())
    root = ET.fromstring(xml)
    envs = root.findall("env")
    assert len(envs) == 2
    names = {e.get("name") for e in envs}
    assert "REGISTA_DSN" in names
    assert "TEST_VAR" in names


def test_generate_xml_includes_on_failure_restart() -> None:
    xml = generate_winsw_xml(_spec())
    root = ET.fromstring(xml)
    failures = root.findall("onfailure")
    assert len(failures) == 2
    assert failures[0].get("action") == "restart"


def test_generate_xml_no_work_domain_identifiers() -> None:
    xml = generate_winsw_xml(_spec())
    forbidden = ["hraedon", "WORK-DOMAIN", "real-host", "production"]
    for token in forbidden:
        assert token not in xml


def _ok_runner(cmd: tuple[str, ...]) -> int:
    return 0


def test_install_writes_xml(tmp_path: Path) -> None:
    result = install_winsw_service(_spec(), winsw_dir=tmp_path, runner=_ok_runner)
    assert result.state is ServiceState.INSTALLED
    assert len(result.files_written) == 1
    xml_path = Path(result.files_written[0])
    assert xml_path.exists()
    assert xml_path.name == "test-service.xml"


def test_install_is_idempotent(tmp_path: Path) -> None:
    spec = _spec()
    first = install_winsw_service(spec, winsw_dir=tmp_path, runner=_ok_runner)
    assert first.state is ServiceState.INSTALLED
    second = install_winsw_service(spec, winsw_dir=tmp_path, runner=_ok_runner)
    assert second.state is ServiceState.ALREADY_INSTALLED


def test_install_dry_run_does_not_write(tmp_path: Path) -> None:
    result = install_winsw_service(_spec(), winsw_dir=tmp_path, dry_run=True)
    assert result.state is ServiceState.INSTALLED
    assert not Path(result.files_written[0]).exists()


def test_remove_existing_service(tmp_path: Path) -> None:
    install_winsw_service(_spec(), winsw_dir=tmp_path, runner=_ok_runner)
    result = remove_winsw_service("test-service", winsw_dir=tmp_path, runner=_ok_runner)
    assert result.state is ServiceState.REMOVED


def test_remove_missing_service_is_not_installed(tmp_path: Path) -> None:
    result = remove_winsw_service("nonexistent", winsw_dir=tmp_path)
    assert result.state is ServiceState.NOT_INSTALLED


def test_remove_dry_run_does_not_delete(tmp_path: Path) -> None:
    install_winsw_service(_spec(), winsw_dir=tmp_path, runner=_ok_runner)
    result = remove_winsw_service("test-service", winsw_dir=tmp_path, dry_run=True, runner=_ok_runner)
    assert result.state is ServiceState.REMOVED
    assert Path(result.files_written[0]).exists()


def test_suite_services_have_valid_specs() -> None:
    for spec in SUITE_SERVICES:
        assert spec.name.startswith("agent-suite-")
        assert spec.executable
        assert spec.arguments
        assert spec.working_dir
        assert spec.log_path
        xml = generate_winsw_xml(spec)
        ET.fromstring(xml)


def test_format_winsw_report_contains_name_and_state() -> None:
    from agent_suite.winsw import WinSWResult

    result = WinSWResult(
        name="test-service",
        state=ServiceState.INSTALLED,
        files_written=["/tmp/test.xml"],
        detail="installed",
    )
    text = format_winsw_report(result)
    assert "test-service" in text
    assert "installed" in text


def test_generate_xml_without_on_failure_restart() -> None:
    spec = WinSWServiceSpec(
        name="test-no-restart",
        description="A test service without restart",
        executable="python",
        arguments="-m test",
        working_dir="C:/test",
        log_path="C:/test/logs",
        on_failure_restart=False,
    )
    xml = generate_winsw_xml(spec)
    root = ET.fromstring(xml)
    assert root.findall("onfailure") == []


def test_generate_xml_escapes_special_characters() -> None:
    spec = WinSWServiceSpec(
        name="test-escape",
        description='A <test> & "service"',
        executable="python",
        arguments="-m test && echo done",
        working_dir="C:/test",
        log_path="C:/test/logs",
    )
    xml = generate_winsw_xml(spec)
    root = ET.fromstring(xml)
    assert root.find("description").text == 'A <test> & "service"'
    assert root.find("arguments").text == "-m test && echo done"


def test_install_calls_runner(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def mock_runner(cmd: tuple[str, ...]) -> int:
        calls.append(cmd)
        return 0

    result = install_winsw_service(_spec(), winsw_dir=tmp_path, runner=mock_runner)
    assert result.state is ServiceState.INSTALLED
    assert len(calls) == 1
    assert calls[0][1] == "install"


def test_install_fails_on_runner_error(tmp_path: Path) -> None:
    def failing_runner(cmd: tuple[str, ...]) -> int:
        return 1

    result = install_winsw_service(_spec(), winsw_dir=tmp_path, runner=failing_runner)
    assert result.state is ServiceState.FAILED
    assert "exited 1" in result.detail


def test_remove_calls_runner(tmp_path: Path) -> None:
    install_winsw_service(_spec(), winsw_dir=tmp_path, runner=lambda cmd: 0)
    calls: list[tuple[str, ...]] = []

    def mock_runner(cmd: tuple[str, ...]) -> int:
        calls.append(cmd)
        return 0

    result = remove_winsw_service("test-service", winsw_dir=tmp_path, runner=mock_runner)
    assert result.state is ServiceState.REMOVED
    assert len(calls) == 1
    assert calls[0][1] == "uninstall"
