"""agent-suite — thin orchestration over the six-component agent suite.

The deterministic core (`cli`, `bootstrap`, `doctor`, `lock`, `config`,
`components`) imports only the standard library. Secret-backend SDKs
(Vault / Azure / Windows) live behind extras and are imported only at the
secret-resolution edge, never in the core — enforced by the architecture test.
"""

__version__ = "0.0.1"
