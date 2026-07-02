from __future__ import annotations

import pytest

from agent_suite.cli import Command, main


def test_subcommands_dispatch() -> None:
    for command in Command:
        assert main([command.value]) == 0


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main([])
