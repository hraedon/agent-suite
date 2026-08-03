"""Develop-against-lock spine symbol gate (WI-057, durable leg).

Unit tests for the pure core. The integration path (real siblings checked out
at umbrella-pinned revisions, locked regista installed) runs in the
``feature-probes`` CI job via ``scripts/check-spine-symbols.py``; here we
exercise the pure collection + resolution logic with synthetic files and
computed export sets, so no regista install is required.
"""

from __future__ import annotations

from pathlib import Path

from agent_suite.spine_symbol_gate import (
    GateResult,
    ImportKind,
    SpineImport,
    _classify,
    collect_regista_imports,
    missing_symbols,
    sibling_test_files,
)

# A synthetic test file exercising every regista import shape, plus imports
# that must be ignored (non-regista, relative).
_SYNTHETIC = """\
import os
import regista
import regista.client
import regista._types as types
from regista import Event
from regista._types import ActorKind
from pathlib import Path
from . import helpers
from regista import client
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_collect_regista_imports_extracts_all_shapes(tmp_path: Path) -> None:
    f = _write(tmp_path, "test_example.py", _SYNTHETIC)
    imports = collect_regista_imports(f)

    assert imports == [
        # import regista
        SpineImport(module="regista", name=None, lineno=2, path=f),
        # import regista.client
        SpineImport(module="regista.client", name=None, lineno=3, path=f),
        # import regista._types as types
        SpineImport(module="regista._types", name=None, lineno=4, path=f),
        # from regista import Event
        SpineImport(module="regista", name="Event", lineno=5, path=f),
        # from regista._types import ActorKind
        SpineImport(module="regista._types", name="ActorKind", lineno=6, path=f),
        # from regista import client
        SpineImport(module="regista", name="client", lineno=9, path=f),
    ]


def test_collect_regista_imports_marks_star_imports(tmp_path: Path) -> None:
    # A star import names no specific symbol: it is collected with star=True
    # and name=None so it can be reported but never flagged missing.
    f = _write(tmp_path, "test_star.py", "from regista import *\n")
    imports = collect_regista_imports(f)
    assert imports == [
        SpineImport(module="regista", name=None, lineno=1, path=f, star=True)
    ]


def test_collect_regista_imports_star_prefix_boundary(tmp_path: Path) -> None:
    # Packages whose name merely starts with "regista" must not be collected.
    f = _write(tmp_path, "test_prefix.py", "import registafoo\nfrom regista_ import x\n")
    assert collect_regista_imports(f) == []


def test_collect_regista_imports_ignores_non_regista_and_relative(
    tmp_path: Path,
) -> None:
    f = _write(tmp_path, "test_example.py", _SYNTHETIC)
    imports = collect_regista_imports(f)
    modules = {imp.module for imp in imports}
    assert modules == {"regista", "regista.client", "regista._types"}
    assert all("pathlib" not in imp.module for imp in imports)
    # The relative `from . import helpers` must not leak in.
    assert all(imp.module.startswith("regista") for imp in imports)


def test_collect_regista_imports_syntax_error_returns_empty(tmp_path: Path) -> None:
    f = _write(tmp_path, "broken.py", "this is not valid python (((\n")
    assert collect_regista_imports(f) == []


def test_collect_regista_imports_missing_file_returns_empty(tmp_path: Path) -> None:
    assert collect_regista_imports(tmp_path / "nope.py") == []


def test_sibling_test_files_finds_tests_dir(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    a = _write(tests, "a.py", "import regista\n")
    nested = tests / "sub"
    nested.mkdir()
    b = _write(nested, "b.py", "import regista\n")

    files = sibling_test_files(tmp_path)
    assert files == sorted([a, b])


def test_sibling_test_files_finds_daemon_tests_dir(tmp_path: Path) -> None:
    dt = tmp_path / "daemon" / "tests"
    dt.mkdir(parents=True)
    w = _write(dt, "w.py", "import regista\n")

    files = sibling_test_files(tmp_path)
    assert files == [w]


def test_sibling_test_files_merges_both_layouts(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    a = _write(tests, "a.py", "")
    dt = tmp_path / "daemon" / "tests"
    dt.mkdir(parents=True)
    b = _write(dt, "b.py", "")

    files = sibling_test_files(tmp_path)
    assert files == sorted([a, b])


def test_sibling_test_files_returns_empty_when_no_tests_dir(tmp_path: Path) -> None:
    assert sibling_test_files(tmp_path) == []


# ---------------------------------------------------------------------------
# Classification + satisfiability matrix for missing_symbols.
# ---------------------------------------------------------------------------


def test_classify_all_four_shapes() -> None:
    assert _classify(SpineImport("regista", None, 1, Path("t.py"))) is ImportKind.PACKAGE
    assert _classify(SpineImport("regista.client", None, 1, Path("t.py"))) is ImportKind.MODULE
    assert _classify(SpineImport("regista", "Event", 1, Path("t.py"))) is ImportKind.FROM_PACKAGE
    assert _classify(
        SpineImport("regista.client", "Foo", 1, Path("t.py"))
    ) is ImportKind.FROM_MODULE


def test_classify_star_import_is_package() -> None:
    # Star imports classify as PACKAGE (always satisfiable): they name no
    # specific symbol, so they can never reference an absent one.
    assert (
        _classify(SpineImport("regista", None, 1, Path("t.py"), star=True))
        is ImportKind.PACKAGE
    )


def test_missing_symbols_plain_package_always_ok() -> None:
    imp = SpineImport("regista", None, 1, Path("t.py"))
    result = missing_symbols(set(), {}, [imp])
    assert result == GateResult(missing=[], unverified=[])


def test_missing_symbols_star_import_never_missing() -> None:
    imp = SpineImport("regista", None, 1, Path("t.py"), star=True)
    result = missing_symbols(set(), {}, [imp])
    assert result == GateResult(missing=[], unverified=[])


def test_missing_symbols_from_package_present_and_missing() -> None:
    present = SpineImport("regista", "Event", 1, Path("t.py"))
    result = missing_symbols({"Event"}, {}, [present])
    assert result.missing == [] and result.unverified == []

    missing = SpineImport("regista", "Ghost", 1, Path("t.py"))
    result = missing_symbols(set(), {}, [missing])
    assert result.missing == [missing] and result.unverified == []


def test_missing_symbols_from_package_submodule_fallback() -> None:
    """`from regista import client` where client is an importable submodule
    (not a top-level attr) must still be treated present."""
    imp = SpineImport("regista", "client", 1, Path("t.py"))
    result = missing_symbols(set(), {"regista.client": {"X"}}, [imp])
    assert result.missing == [] and result.unverified == []


def test_missing_symbols_import_module_submodule_and_top_attr() -> None:
    by_submodule = SpineImport("regista.client", None, 1, Path("t.py"))
    result = missing_symbols(set(), {"regista.client": {"X"}}, [by_submodule])
    assert result.missing == []

    by_top_attr = SpineImport("regista.client", None, 1, Path("t.py"))
    result = missing_symbols({"client"}, {}, [by_top_attr])
    assert result.missing == []

    missing = SpineImport("regista.missing_sub", None, 1, Path("t.py"))
    result = missing_symbols(set(), {}, [missing])
    assert result.missing == [missing]


def test_missing_symbols_from_module_present_and_missing() -> None:
    present = SpineImport("regista._types", "ActorKind", 1, Path("t.py"))
    result = missing_symbols(set(), {"regista._types": {"ActorKind"}}, [present])
    assert result.missing == []

    missing = SpineImport("regista._types", "Ghost", 1, Path("t.py"))
    result = missing_symbols(set(), {"regista._types": {"ActorKind"}}, [missing])
    assert result.missing == [missing]


def test_missing_symbols_from_module_unverified_not_missing() -> None:
    """When the submodule wasn't introspected at all, the import is
    UNVERIFIED (benefit of the doubt), never MISSING."""
    imp = SpineImport("regista._types", "ActorKind", 1, Path("t.py"))
    result = missing_symbols(set(), {}, [imp])
    assert result.missing == [] and result.unverified == [imp]


def test_missing_symbols_mixed_batch_counts() -> None:
    imports = [
        SpineImport("regista", None, 1, Path("t.py")),  # package — ok
        SpineImport("regista", "Event", 2, Path("t.py")),  # present
        SpineImport("regista", "Ghost", 3, Path("t.py")),  # missing
        SpineImport("regista._types", "ActorKind", 4, Path("t.py")),  # present
        SpineImport("regista._types", "Nope", 5, Path("t.py")),  # missing
        SpineImport("regista.unseen", "X", 6, Path("t.py")),  # unverified
        SpineImport("regista", None, 7, Path("t.py"), star=True),  # star — ok
    ]
    result = missing_symbols(
        {"Event"}, {"regista._types": {"ActorKind"}}, imports
    )
    assert [imp.lineno for imp in result.missing] == [3, 5]
    assert [imp.lineno for imp in result.unverified] == [6]
