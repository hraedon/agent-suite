"""agent-suite — thin orchestration over the six-component agent suite.

The deterministic core (`cli`, `bootstrap`, `doctor`, `lock`, `config`,
`components`) imports only the standard library. Secret-backend SDKs
(Vault / Azure / Windows) live behind extras and are imported only at the
secret-resolution edge, never in the core — enforced by the architecture test.
"""

# The single source of the umbrella wheel's version (pyproject reads it via
# hatchling's dynamic-version hook). It is NOT an independent number: WI-035
# requires it to be the PEP 440 form of the suite release identity declared in
# data/release-board.json, and tests/test_packaging.py asserts exactly that —
# so cutting 1.0.0-rc.3 forces bumping this line, and two releases can never
# attach an identically named umbrella wheel with different contents.
__version__ = "1.0.0.dev0"
