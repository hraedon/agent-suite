#!/usr/bin/env python3
"""Develop-against-lock spine symbol gate (WI-057, durable leg).

The enforcement point that catches the failure class where a sibling's *test*
files import a symbol from ``regista`` that exists on regista's ``main`` but
NOT in the released/locked spine version. The sibling's CI then runs against
the locked spine (the ``SUITE.lock`` pin) and fails — red-maining the sibling
independent of any PR's own delta. This gate catches that at the umbrella
(agent-suite) before it lands, in the ``feature-probes`` CI job where every
sibling is checked out at its ``SUITE.lock``-pinned revision and the locked
regista is installed into the venv (so the regista we import IS the locked
spine — that is the whole authority of the check).

Reads the umbrella ``SUITE.lock`` to enumerate the sibling components, scans
each checked-out sibling's test directory for regista imports, and resolves
each against the installed regista. Exit code:

    0 — every imported symbol is present in the locked spine (or there is
        nothing to check: no sibling checkouts, or none import regista).
    1 — at least one imported symbol is MISSING from the locked spine, OR
        (with ``--strict``) at least one import was UNVERIFIED.
    2 — the installed regista (the locked spine) could not be imported, so
        the gate cannot run — an environment problem, not a gate failure.

With ``--strict``, an import whose submodule could not be introspected
(UNVERIFIED) is also treated as a failure; without it, unverified imports are
reported but not fatal, to avoid false positives from submodules that fail to
import for environmental reasons.

Usage:
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-spine-symbols.py
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-spine-symbols.py --strict
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import tomllib
from pathlib import Path

from agent_suite.spine_symbol_gate import (
    SpineImport,
    collect_regista_imports,
    missing_symbols,
    sibling_test_files,
)

SPINE_PACKAGE = "regista"


def _format_finding(imp: SpineImport) -> str:
    symbol = imp.name if imp.name else imp.module
    try:
        where = imp.path.relative_to(Path.cwd())
    except ValueError:
        where = imp.path
    return f"      {where}:{imp.lineno}  {symbol}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Develop-against-lock spine symbol gate (WI-057)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail (exit 1) when an import targets a submodule that could "
        "not be introspected against the locked spine (unverified).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    umbrella_path = repo_root / "SUITE.lock"
    if not umbrella_path.is_file():
        print(
            f"check-spine-symbols: no umbrella SUITE.lock at {umbrella_path}",
            file=sys.stderr,
        )
        return 2
    umbrella_text = umbrella_path.read_text(encoding="utf-8")
    umbrella = tomllib.loads(umbrella_text)
    components = umbrella.get("components", {})

    # WI-058 will consolidate the workspace-root env var behind
    # ``agent_suite.lock.resolve_workspace_root``; until that lands this script
    # reads AGENT_SUITE_SIBLINGS_ROOT, matching the other sibling scanners.
    siblings_root = Path(os.environ.get("AGENT_SUITE_SIBLINGS_ROOT", "/tmp/siblings"))

    # Collect regista imports per checked-out sibling.
    per_sibling: dict[str, list[SpineImport]] = {}
    info_no_tests: list[str] = []
    for member in sorted(components):
        if member == SPINE_PACKAGE:
            continue
        member_root = siblings_root / member
        if not member_root.is_dir():
            continue
        test_files = sibling_test_files(member_root)
        if not test_files:
            info_no_tests.append(member)
            continue
        imports: list[SpineImport] = []
        for tf in test_files:
            imports.extend(collect_regista_imports(tf))
        per_sibling[member] = imports

    all_imports: list[SpineImport] = [
        imp for imports in per_sibling.values() for imp in imports
    ]

    print("develop-against-lock spine symbol gate (WI-057)")
    print(f"siblings root: {siblings_root}")
    print("")

    for member in info_no_tests:
        print(f"  [n/a ] {member:<28} (no tests directory)")

    if not per_sibling:
        print("no sibling checkouts present; nothing to check.")
        return 0

    if not all_imports:
        for member in sorted(per_sibling):
            print(f"  [ok  ] {member:<28} (no regista imports)")
        print("")
        print("no regista imports found in any sibling's tests; nothing to check.")
        return 0

    # Imports to resolve — the locked spine must be importable. importlib (rather
    # than ``import regista``) keeps this mypy --strict clean without depending
    # on regista stubs, and is functionally identical.
    try:
        spine = importlib.import_module(SPINE_PACKAGE)
    except ImportError:
        print(
            f"check-spine-symbols: the locked spine ({SPINE_PACKAGE}) is not "
            "importable in this environment; cannot resolve symbols.",
            file=sys.stderr,
        )
        return 2
    top_exports: set[str] = set(dir(spine))

    # Introspect only the submodules actually referenced by the imports, so we
    # never import the world. A referenced submodule that fails to import is
    # simply absent from submodule_attrs; missing_symbols treats that as
    # MISSING (or UNVERIFIED for ``from regista.x import name``).
    candidate_submodules: set[str] = set()
    for imp in all_imports:
        if imp.name is None:
            # `import regista` references nothing; `import regista.x` does.
            if imp.module.startswith(f"{SPINE_PACKAGE}."):
                candidate_submodules.add(imp.module)
        elif imp.module.startswith(f"{SPINE_PACKAGE}."):
            # `from regista.x import name`.
            candidate_submodules.add(imp.module)
        elif imp.module == SPINE_PACKAGE:
            # `from regista import name` — name may itself be a submodule.
            candidate_submodules.add(f"{SPINE_PACKAGE}.{imp.name}")

    submodule_attrs: dict[str, set[str]] = {}
    for mod in sorted(candidate_submodules):
        try:
            submodule = importlib.import_module(mod)
        except ImportError:
            continue
        submodule_attrs[mod] = set(dir(submodule))

    # Resolve per sibling and report.
    exit_code = 0
    for member in sorted(per_sibling):
        imports = per_sibling[member]
        result = missing_symbols(top_exports, submodule_attrs, imports)
        marks: list[str] = []
        if result.missing:
            marks.append(f"{len(result.missing)} missing")
        if result.unverified:
            marks.append(f"{len(result.unverified)} unverified")
        if result.missing:
            status = "FAIL"
        elif result.unverified:
            status = "?   "
        else:
            status = "ok  "
        summary = ", ".join(marks) if marks else "all present"
        print(
            f"  [{status}] {member:<28} "
            f"({len(imports)} imports scanned; {summary})"
        )
        for imp in result.missing:
            print(_format_finding(imp))
        if result.missing:
            exit_code = 1
        elif args.strict and result.unverified:
            exit_code = 1

    print("")
    if exit_code == 1:
        print(
            "FAILURE: at least one symbol imported by sibling tests is absent "
            "from the locked spine release."
        )
    else:
        print("all regista imports are satisfied by the locked spine release.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
