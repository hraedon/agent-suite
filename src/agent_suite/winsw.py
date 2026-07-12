"""WinSW (Windows Service Wrapper) service configuration generator.

Generates WinSW XML configuration files for suite services and provides
idempotent install/remove operations. The module is stdlib-only — it
generates XML files and delegates the actual ``winsw.exe install`` call to
an injectable runner protocol (same pattern as ``schedule.py``).

The WinSW binary itself is an operator prerequisite — this module does not
download or install it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree as ET


class ServiceState(Enum):
    INSTALLED = "installed"
    ALREADY_INSTALLED = "already_installed"
    REMOVED = "removed"
    NOT_INSTALLED = "not_installed"
    FAILED = "failed"


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> int:
        """Run a command and return the exit code."""
        ...


def _default_runner(cmd: tuple[str, ...]) -> int:
    import subprocess

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode


@dataclass(frozen=True)
class WinSWServiceSpec:
    name: str
    description: str
    executable: str
    arguments: str
    working_dir: str
    log_path: str
    env_vars: dict[str, str] = field(default_factory=dict)
    on_failure_restart: bool = True


@dataclass
class WinSWResult:
    name: str
    state: ServiceState
    files_written: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "files_written": self.files_written,
            "detail": self.detail,
        }


SUITE_SERVICES: tuple[WinSWServiceSpec, ...] = (
    WinSWServiceSpec(
        name="agent-suite-dossier",
        description="Dossier — human web face for the agent suite",
        executable="python",
        arguments="-m dossier",
        working_dir="C:/ProgramData/agent-suite",
        log_path="C:/ProgramData/agent-suite/logs",
    ),
    WinSWServiceSpec(
        name="agent-suite-wake",
        description="Agent-wake — external signaling daemon",
        executable="python",
        arguments="-m agent_wake",
        working_dir="C:/ProgramData/agent-suite",
        log_path="C:/ProgramData/agent-suite/logs",
    ),
)


def generate_winsw_xml(spec: WinSWServiceSpec) -> str:
    """Generate the WinSW XML configuration for a service."""
    root = ET.Element("service")

    ET.SubElement(root, "id").text = spec.name
    ET.SubElement(root, "name").text = spec.name
    ET.SubElement(root, "description").text = spec.description

    ET.SubElement(root, "executable").text = spec.executable
    ET.SubElement(root, "arguments").text = spec.arguments
    ET.SubElement(root, "workingdirectory").text = spec.working_dir
    ET.SubElement(root, "logpath").text = spec.log_path

    if spec.on_failure_restart:
        ET.SubElement(root, "onfailure", {"action": "restart", "delay": "10 sec"})
        ET.SubElement(root, "onfailure", {"action": "reboot", "delay": "60 sec"})

    for key, value in sorted(spec.env_vars.items()):
        env_elem = ET.SubElement(root, "env")
        env_elem.set("name", key)
        env_elem.set("value", value)

    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + "\n"


def _xml_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def install_winsw_service(
    spec: WinSWServiceSpec,
    *,
    winsw_dir: Path = Path("C:/ProgramData/agent-suite/services"),
    winsw_exe: str = "winsw.exe",
    dry_run: bool = False,
    runner: Runner = _default_runner,
) -> WinSWResult:
    """Generate XML and install the service. Idempotent.

    Writes the WinSW XML config and then invokes ``winsw.exe install`` via
    the injectable runner. On non-Windows or when the runner fails, the
    XML is still written but the state is ``FAILED``.
    """
    xml_content = generate_winsw_xml(spec)
    xml_path = winsw_dir / f"{spec.name}.xml"

    if xml_path.exists():
        existing = xml_path.read_text(encoding="utf-8")
        if _xml_hash(existing) == _xml_hash(xml_content):
            return WinSWResult(
                name=spec.name,
                state=ServiceState.ALREADY_INSTALLED,
                files_written=[str(xml_path)],
                detail="service XML unchanged",
            )

    if dry_run:
        return WinSWResult(
            name=spec.name,
            state=ServiceState.INSTALLED,
            files_written=[str(xml_path)],
            detail="dry-run: XML would be written (not acted)",
        )

    try:
        winsw_dir.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(xml_content, encoding="utf-8")
    except OSError as exc:
        return WinSWResult(
            name=spec.name,
            state=ServiceState.FAILED,
            detail=f"failed to write {xml_path}: {exc}",
        )

    try:
        exit_code = runner((winsw_exe, "install", str(xml_path)))
    except Exception as exc:
        return WinSWResult(
            name=spec.name,
            state=ServiceState.FAILED,
            files_written=[str(xml_path)],
            detail=f"runner failed: {exc}",
        )
    if exit_code != 0:
        return WinSWResult(
            name=spec.name,
            state=ServiceState.FAILED,
            files_written=[str(xml_path)],
            detail=f"winsw.exe install exited {exit_code}",
        )

    return WinSWResult(
        name=spec.name,
        state=ServiceState.INSTALLED,
        files_written=[str(xml_path)],
        detail="service installed",
    )


def remove_winsw_service(
    name: str,
    *,
    winsw_dir: Path = Path("C:/ProgramData/agent-suite/services"),
    winsw_exe: str = "winsw.exe",
    dry_run: bool = False,
    runner: Runner = _default_runner,
) -> WinSWResult:
    """Remove a WinSW service. Idempotent — missing service is NOT_INSTALLED."""
    xml_path = winsw_dir / f"{name}.xml"

    if not xml_path.exists():
        return WinSWResult(
            name=name,
            state=ServiceState.NOT_INSTALLED,
            detail="service XML not found",
        )

    if dry_run:
        return WinSWResult(
            name=name,
            state=ServiceState.REMOVED,
            files_written=[str(xml_path)],
            detail="dry-run: XML would be removed",
        )

    try:
        runner((winsw_exe, "uninstall", str(xml_path)))
    except Exception:
        pass

    try:
        xml_path.unlink(missing_ok=True)
    except OSError as exc:
        return WinSWResult(
            name=name,
            state=ServiceState.FAILED,
            detail=f"failed to remove {xml_path}: {exc}",
        )

    return WinSWResult(
        name=name,
        state=ServiceState.REMOVED,
        detail="service removed",
    )


def format_winsw_report(result: WinSWResult) -> str:
    """Human-readable summary for a WinSW install/remove."""
    lines: list[str] = [f"  {result.name:<30} {result.state.value:<20} {result.detail}"]
    for f in result.files_written:
        lines.append(f"    {f}")
    return "\n".join(lines)
