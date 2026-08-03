"""Develop-against-lock spine symbol gate (WI-057, durable leg).

The failure class this catches: a sibling component's *test* files import a
symbol from ``regista`` that exists on regista's ``main`` but NOT in the
released/locked spine version. The sibling's CI then runs against the locked
spine (the ``SUITE.lock`` pin) and fails — red-maining the sibling independent
of any PR's own delta. This gate catches that at the umbrella (agent-suite)
before it lands.

Pure + stdlib-only (``ast``/``dataclasses``/``enum``/``pathlib``), per the
thin-orchestration charter: the core takes paths and pre-computed export sets as
input and performs no importing and no I/O beyond reading the test files. All
knowledge of "what does the locked spine export" is supplied by the wrapper,
so the resolution logic is unit-testable without regista installed.
``scripts/check-spine-symbols.py`` is the thin wrapper that reads the checked-
out siblings, imports the locked spine, builds the export sets, and calls
:func:`missing_symbols`.

The spine package name is ``regista`` (``SPINE_PACKAGE``); the core never
imports it. The satisfiability rules in :func:`missing_symbols` mirror how
Python actually resolves each import shape.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never

SPINE_PACKAGE = "regista"


class ImportKind(Enum):
    """The closed set of regista import shapes an AST walk recognizes."""

    PACKAGE = "package"  # import regista
    MODULE = "module"  # import regista.foo [as bar]
    FROM_PACKAGE = "from_package"  # from regista import name
    FROM_MODULE = "from_module"  # from regista.foo import name


@dataclass(frozen=True)
class SpineImport:
    """One regista import collected from a test file.

    ``name`` is ``None`` for plain ``import regista`` / ``import regista.foo``
    (the whole module is the target); for ``from`` imports it is the imported
    symbol. ``module`` is the dotted module path (``regista`` or
    ``regista.foo``). ``star`` marks ``from regista import *`` — collected for
    evidence but never classifiable as missing (it names no specific symbol).
    """

    module: str
    name: str | None
    lineno: int
    path: Path
    star: bool = False


def _classify(imp: SpineImport) -> ImportKind:
    """Map an import's ``module``/``name`` onto its :class:`ImportKind`."""
    if imp.star:
        # A star import names no specific symbol; it is satisfiable whenever
        # the package itself is, which the wrapper guarantees before resolving.
        return ImportKind.PACKAGE
    if imp.name is None:
        return ImportKind.PACKAGE if imp.module == SPINE_PACKAGE else ImportKind.MODULE
    return (
        ImportKind.FROM_PACKAGE
        if imp.module == SPINE_PACKAGE
        else ImportKind.FROM_MODULE
    )


def collect_regista_imports(test_file: Path) -> list[SpineImport]:
    """AST-parse one test file and return every regista import it contains.

    Returns ``[]`` (without raising) on a syntax error, a read error, or a
    decoding error — a malformed test file is not this gate's concern. Relative
    imports (``from . import x``) and non-regista imports are skipped. Star
    imports (``from regista import *``) are collected with ``star=True``; they
    name no specific symbol, so :func:`missing_symbols` never fails them.
    Dynamic imports (``importlib.import_module``, ``__import__``, ``exec``) are
    invisible to an AST scan by construction — a documented limitation: this
    gate covers the static-import failure class, not deliberate evasion.
    """
    try:
        source = test_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(test_file))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    imports: list[SpineImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted = alias.name
                if dotted == SPINE_PACKAGE or dotted.startswith(f"{SPINE_PACKAGE}."):
                    imports.append(
                        SpineImport(
                            module=dotted,
                            name=None,
                            lineno=node.lineno,
                            path=test_file,
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Relative imports (from . import x) have level > 0 and are not
            # regista imports; node.module may be None for `from . import x`.
            if node.level and node.level > 0:
                continue
            if node.module == SPINE_PACKAGE or node.module.startswith(
                f"{SPINE_PACKAGE}."
            ):
                for alias in node.names:
                    imports.append(
                        SpineImport(
                            module=node.module,
                            name=None if alias.name == "*" else alias.name,
                            lineno=node.lineno,
                            path=test_file,
                            star=alias.name == "*",
                        )
                    )
    return imports


def sibling_test_files(sibling_root: Path) -> list[Path]:
    """Return the sorted ``*.py`` files under a sibling's test directories.

    Most siblings keep tests under ``tests/``; agent-wake nests them under
    ``daemon/tests/``. Both are detected and merged. Returns ``[]`` when neither
    directory exists.
    """
    files: list[Path] = []
    for subdir in ("tests", "daemon/tests"):
        candidate = sibling_root / subdir
        if candidate.is_dir():
            files.extend(candidate.rglob("*.py"))
    return sorted(files)


@dataclass(frozen=True)
class GateResult:
    """The outcome of resolving a batch of imports against the locked spine.

    ``missing`` imports are absent from the locked spine — a gate failure.
    ``unverified`` imports target a submodule the wrapper could not introspect;
    they are reported but not counted as failures unless ``--strict`` is set.
    """

    missing: list[SpineImport]
    unverified: list[SpineImport]


def missing_symbols(
    top_exports: set[str],
    submodule_attrs: dict[str, set[str]],
    imports: list[SpineImport],
) -> GateResult:
    """Resolve each import against the locked spine's exports.

    ``top_exports`` is the attribute set of the ``regista`` package itself
    (the wrapper passes ``set(dir(regista))``); ``submodule_attrs`` maps each
    introspected dotted submodule (``regista.foo``) to its attribute set. The
    satisfiability rules mirror how Python resolves each shape:

    * ``import regista`` — always satisfiable.
    * ``import regista.x`` — satisfiable iff ``regista.x`` is an importable
      submodule OR ``x`` is re-exported as a top-level attribute.
    * ``from regista import name`` — satisfiable iff ``name`` is a top-level
      export OR ``regista.name`` is an importable submodule.
    * ``from regista.x import name`` — satisfiable iff ``regista.x`` is a
      submodule that exports ``name``. If ``regista.x`` could not be
      introspected at all, the import is unverified (benefit of the doubt)
      rather than missing.

    Star imports are classified as :attr:`ImportKind.PACKAGE` and therefore
    always satisfiable: ``from regista import *`` names no specific symbol, so
    it cannot reference one that is absent.
    """
    missing: list[SpineImport] = []
    unverified: list[SpineImport] = []
    for imp in imports:
        kind = _classify(imp)
        match kind:
            case ImportKind.PACKAGE:
                # `import regista` (and star imports) — always satisfiable
                # once the package exists.
                continue
            case ImportKind.MODULE:
                # `import regista.x` — satisfiable iff regista.x is an importable
                # submodule OR x is re-exported as a top-level attribute.
                suffix = imp.module[len(f"{SPINE_PACKAGE}."):]
                if imp.module in submodule_attrs or suffix in top_exports:
                    continue
                missing.append(imp)
            case ImportKind.FROM_PACKAGE:
                # `from regista import name` — satisfiable iff name is a top-
                # level export OR regista.name is an importable submodule.
                assert imp.name is not None
                if imp.name in top_exports or f"{SPINE_PACKAGE}.{imp.name}" in submodule_attrs:
                    continue
                missing.append(imp)
            case ImportKind.FROM_MODULE:
                # `from regista.x import name` — satisfiable iff regista.x is a
                # submodule that exports name. If regista.x could not be
                # introspected, give the benefit of the doubt (unverified).
                assert imp.name is not None
                attrs = submodule_attrs.get(imp.module)
                if attrs is None:
                    unverified.append(imp)
                elif imp.name in attrs:
                    continue
                else:
                    missing.append(imp)
            case _ as unreachable:
                assert_never(unreachable)
    return GateResult(missing=missing, unverified=unverified)
