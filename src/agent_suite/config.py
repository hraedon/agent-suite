"""Suite.env loader — read the layered suite config into os.environ.

The suite config contract (bootstrap-contract §2) says precedence is:

    process env  >  per-user suite.env  >  system suite.env  >  tool default

This module loads suite.env files and injects their values into
``os.environ`` **only for keys that are not already set** — so explicit
process env always wins. This means operators don't need to manually
``source suite.env`` before running ``agent-suite bootstrap`` or
``agent-suite doctor``; the CLI loads it automatically.

The per-user file is at ``~/.config/agent-suite/suite.env`` (Linux) or
``%APPDATA%/agent-suite/suite.env`` (Windows), overridable via
``AGENT_SUITE_CONFIG``. The system file is at
``/etc/agent-suite/suite.env`` (Linux) or
``%ProgramData%/agent-suite/suite.env`` (Windows).
"""

from __future__ import annotations

import os
from pathlib import Path


def user_suite_env_path() -> Path:
    override = os.environ.get("AGENT_SUITE_CONFIG")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "agent-suite" / "suite.env"
    return Path.home() / ".config" / "agent-suite" / "suite.env"


def system_suite_env_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("ProgramData", r"C:\ProgramData")
        return Path(base) / "agent-suite" / "suite.env"
    return Path("/etc/agent-suite/suite.env")


def _parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        result[key] = value
    return result


def load_suite_env_into_environ(
    *,
    user_path: Path | None = None,
    system_path: Path | None = None,
) -> int:
    """Load suite.env into ``os.environ`` for keys not already set.

    Returns the number of keys injected. Process env always wins — a key
    already in ``os.environ`` is never overwritten.
    """
    if user_path is None:
        user_path = user_suite_env_path()
    if system_path is None:
        system_path = system_suite_env_path()

    merged: dict[str, str] = {}
    merged.update(_parse_env_file(system_path))
    merged.update(_parse_env_file(user_path))

    injected = 0
    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value
            injected += 1
    return injected
