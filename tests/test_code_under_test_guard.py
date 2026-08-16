"""WI-075 meta-guard falsifiers: prove the code-under-test guard rejects.

The guard in ``conftest.pytest_configure`` refuses to start a session when
``agent_suite`` imports from outside this repo root — the WI-075 failure mode,
where a worktree's unprovisioned venv makes ``uv run pytest`` fall back to a
PATH pytest that imports the PRIMARY checkout's code. A guard that has never
been shown to reject anything is a tautology (process-calibration §5), so this
file exercises the pure function's deny cases directly, plus the live session
as the allow case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import agent_suite
from tests.conftest import REPO_ROOT, CodeUnderTestError, require_code_under_test


def test_live_session_imports_from_this_repo() -> None:
    """The allow case, live: this very session's agent_suite is ours."""
    resolved = require_code_under_test(
        REPO_ROOT, getattr(agent_suite, "__file__", None), "agent_suite"
    )
    assert resolved.is_relative_to(REPO_ROOT.resolve())


def test_module_outside_repo_root_is_rejected(tmp_path: Path) -> None:
    """The deny case: a module file under a foreign root is refused, and the
    message carries the remediation (the exact uv invocation and WI-075)."""
    foreign = tmp_path / "elsewhere" / "src" / "agent_suite" / "__init__.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("")
    with pytest.raises(CodeUnderTestError) as excinfo:
        require_code_under_test(REPO_ROOT, str(foreign), "agent_suite")
    message = str(excinfo.value)
    assert "WI-075" in message
    assert "uv run --frozen --extra dev pytest" in message


def test_missing_module_file_is_rejected() -> None:
    """A namespace-package import (no __file__) proves nothing — refuse."""
    with pytest.raises(CodeUnderTestError, match="no __file__"):
        require_code_under_test(REPO_ROOT, None, "agent_suite")


def test_symlinked_repo_root_still_allows(tmp_path: Path) -> None:
    """/projects is a symlink on the dev boxes; resolution must not produce a
    false rejection when root and module are the same tree via different
    spellings."""
    real_root = tmp_path / "real"
    module = real_root / "src" / "agent_suite" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("")
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    resolved = require_code_under_test(
        link_root, str(link_root / "src" / "agent_suite" / "__init__.py"), "agent_suite"
    )
    assert resolved == module.resolve()
