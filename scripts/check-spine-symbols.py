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
    1 — at least one imported symbol is MISSING from the locked spine; with
        ``--strict``, also when at least one import was UNVERIFIED or at
        least one umbrella-listed sibling has no checkout under the root.
    2 — the installed regista (the locked spine) could not be imported, so
        the gate cannot run — an environment problem, not a gate failure.

With ``--strict``, an import whose submodule could not be introspected
(UNVERIFIED) is also treated as a failure; without it, unverified imports are
reported but not fatal, to avoid false positives from submodules that fail to
import for environmental reasons. Umbrella-listed siblings with no checkout
are always reported (``[gone]``) so the gate can never silently skip a
component; they fail only under ``--strict`` so partial local checkouts stay
usable.

Limitations (by construction): the scan is static AST over *test* files.
Dynamic imports (``importlib.import_module``, ``__import__``, ``exec``) are
invisible to it, and runtime (non-test) imports are out of scope — the gate
targets the WI-057 failure class (sibling tests drifting ahead of the locked
spine), which test-file scanning covers because a sibling's tests import its
runtime surface.

Usage:
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-spine-symbols.py
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-spine-symbols.py --strict
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from pathlib import Path

from agent_suite.lock import resolve_workspace_root
from agent_suite.spine_symbol_gate import (
    SPINE_PACKAGE,
    SpineImport,
    candidate_submodules,
    collect_regista_imports,
    missing_symbols,
    sibling_test_files,
)


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

    # WI-058 consolidated the workspace-root env var behind
    # ``agent_suite.lock.resolve_workspace_root`` (precedence: canonical
    # SUITE_WORKSPACE_ROOT > back-compat AGENT_SUITE_SIBLINGS_ROOT > default),
    # so this script reads the same root as the other sibling scanners.
    siblings_root = resolve_workspace_root(Path("/tmp/siblings"))

    # Collect regista imports per checked-out sibling. Umbrella-listed members
    # with no checkout are reported as [gone] — the gate must never silently
    # skip a component (adversarial review WI-057 R1); --strict fails on them.
    per_sibling: dict[str, list[SpineImport]] = {}
    info_no_tests: list[str] = []
    missing_checkouts: list[str] = []
    for member in sorted(components):
        if member == SPINE_PACKAGE:
            continue
        member_root = siblings_root / member
        if not member_root.is_dir():
            missing_checkouts.append(member)
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

    for member in missing_checkouts:
        print(f"  [gone] {member:<28} (listed in SUITE.lock, no checkout)")
    for member in info_no_tests:
        print(f"  [n/a ] {member:<28} (no tests directory)")

    if not per_sibling:
        if missing_checkouts and args.strict:
            print("")
            print(
                "FAILURE: umbrella-listed siblings have no checkout under the "
                "siblings root; nothing could be checked."
            )
            return 1
        print("no sibling checkouts present; nothing to check.")
        return 0

    if not all_imports:
        for member in sorted(per_sibling):
            print(f"  [ok  ] {member:<28} (no regista imports)")
        print("")
        print("no regista imports found in any sibling's tests; nothing to check.")
        if missing_checkouts and args.strict:
            print(
                "FAILURE: umbrella-listed siblings have no checkout under the "
                "siblings root."
            )
            return 1
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
    # never import the world. A referenced submodule that fails to import (or
    # raises at import time, e.g. a missing optional dependency) is simply
    # absent from submodule_attrs; missing_symbols treats that as MISSING (or
    # UNVERIFIED for ``from regista.x import name``). Names already satisfied
    # as top-level exports need no submodule probe. The pure collection lives
    # in agent_suite.spine_symbol_gate.candidate_submodules; see WI-066 for why
    # from-module star imports (``from regista.foo import *``) must be probed.
    candidates: set[str] = candidate_submodules(top_exports, all_imports)

    submodule_attrs: dict[str, set[str]] = {}
    submodule_objs: dict[str, object] = {}
    for mod in sorted(candidates):
        try:
            submodule = importlib.import_module(mod)
        except Exception:
            continue
        submodule_attrs[mod] = set(dir(submodule))
        submodule_objs[mod] = submodule

    def _actually_missing(imp: SpineImport) -> bool:
        # hasattr is the final authority (it is what from-import binding does):
        # it also resolves PEP 562 lazy attributes that dir() does not list, so
        # a future lazy-export in the spine cannot false-positive this gate.
        if imp.name is None:
            return True
        if imp.module == SPINE_PACKAGE:
            return not hasattr(spine, imp.name)
        target = submodule_objs.get(imp.module)
        return not (target is not None and hasattr(target, imp.name))

    # Resolve per sibling and report.
    exit_code = 0
    for member in sorted(per_sibling):
        imports = per_sibling[member]
        result = missing_symbols(top_exports, submodule_attrs, imports)
        missing = [imp for imp in result.missing if _actually_missing(imp)]
        marks: list[str] = []
        if missing:
            marks.append(f"{len(missing)} missing")
        if result.unverified:
            marks.append(f"{len(result.unverified)} unverified")
        if missing:
            status = "FAIL"
        elif result.unverified:
            status = "unv "
        else:
            status = "ok  "
        summary = ", ".join(marks) if marks else "all present"
        print(
            f"  [{status}] {member:<28} "
            f"({len(imports)} imports scanned; {summary})"
        )
        for imp in missing:
            print(_format_finding(imp))
        if missing:
            exit_code = 1
        elif args.strict and result.unverified:
            exit_code = 1

    if missing_checkouts and args.strict:
        exit_code = 1

    print("")
    if exit_code == 1:
        print(
            "FAILURE: the develop-against-lock gate found imports the locked "
            "spine release does not satisfy (missing symbols, or --strict "
            "failures: unverified imports / missing sibling checkouts)."
        )
    else:
        print("all regista imports are satisfied by the locked spine release.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
