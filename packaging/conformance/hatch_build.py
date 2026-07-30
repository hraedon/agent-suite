"""Hatch build hook for the standalone agent-suite-conformance distribution.

ONE source of truth: ``src/agent_suite/conformance/`` at the monorepo root. This
hook force-includes that subtree into ``agent_suite/conformance/`` in both the
wheel and the sdist — with NO symlink and NO maintained copy.

Why not a symlink: Git for Windows with ``core.symlinks=false`` (the default on
many Windows setups) checks a symlink out as a plain text file holding the link
target, so an in-project link to the source subtree silently stops resolving and
the build ships nothing. Why not a copy: the kit must never be duplicated
(Plan 018 WI-2) — a copied subtree drifts from the maintained one.

Two build contexts, resolved in ``initialize``:

* **Monorepo source tree** — the canonical ``../../src/agent_suite/conformance``
  exists (relative to this project dir); force-include it.
* **Wheel-from-sdist** — the sdist already materialized the subtree at
  ``agent_suite/conformance`` (and shipped this very hook, see below); the
  canonical path is gone, so force-include the materialized local subtree.

For the sdist target the hook also force-includes ``hatch_build.py`` itself and
``README.md``, so an extracted sdist is fully self-contained and the
wheel-from-sdist step can run this hook. ``build_data['force_include']`` takes
precedence over the static ``[tool.hatch...force-include]`` on conflict, so the
hook's dynamically chosen source always wins.

The hook is deliberately permissive for **editable** installs: a PEP 660
editable build uses a temporary, reduced source tree in which neither the
canonical nor the sdist-local subtree is present, and the editable wheel needs
no real files (it is a path shim back to the source). Raising there would break
``pip install -e``; the two real build contexts (source tree, wheel-from-sdist)
still fail loudly when the source is genuinely absent.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# The maintained subtree, relative to this project dir (packaging/conformance).
_CANONICAL_SOURCE = os.path.join("..", "..", "src", "agent_suite", "conformance")
# Where the sdist materializes the subtree — and where the wheel expects it.
_LOCAL_PACKAGE = os.path.join("agent_suite", "conformance")
# This file, so the sdist carries the hook the wheel-from-sdist build needs.
_HOOK_SCRIPT = "hatch_build.py"


class ConformanceSourceHook(BuildHookInterface[Any]):
    """Force-include the conformance source from wherever it actually lives."""

    PLUGIN_NAME = "conformance-source"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        force_include: dict[str, str] = build_data["force_include"]

        canonical = os.path.normpath(os.path.join(self.root, _CANONICAL_SOURCE))
        local = os.path.normpath(os.path.join(self.root, _LOCAL_PACKAGE))

        if os.path.isdir(canonical):
            # Building from the monorepo source tree.
            source = canonical
        elif os.path.isdir(local):
            # Building a wheel from an extracted sdist: the subtree is already
            # materialized here by the sdist build.
            source = local
        elif version == "editable":
            # PEP 660 editable build from a reduced temp tree — nothing to ship.
            return
        else:
            msg = (
                "agent-suite-conformance: cannot locate the conformance source. "
                f"Expected the monorepo source at {canonical!r} or a "
                f"materialized sdist subtree at {local!r}; neither exists. Build "
                "from the agent-suite source tree or from a complete sdist."
            )
            raise FileNotFoundError(msg)

        # Ship the subtree as a PEP 420 namespace portion (no agent_suite/__init__.py).
        force_include[source] = _LOCAL_PACKAGE

        if self.target_name == "sdist":
            # Ship the hook itself so an extracted sdist can run it (the
            # wheel-from-sdist step). hatchling also auto-includes the configured
            # build script in the sdist; this explicit entry is belt-and-suspenders
            # that documents the requirement and the force_include mechanism.
            hook_path = os.path.normpath(os.path.join(self.root, _HOOK_SCRIPT))
            force_include[hook_path] = _HOOK_SCRIPT
            # Ship the README so an `sdist`-only consumer renders the description.
            readme_path = os.path.normpath(os.path.join(self.root, "README.md"))
            if os.path.isfile(readme_path):
                force_include[readme_path] = "README.md"
