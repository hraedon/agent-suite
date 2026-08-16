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

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

if TYPE_CHECKING:
    from agent_suite.entra import EntraConfig


MEMORY_ENGINE_ENV = "AGENT_NOTES_MEMORY_ENGINE"
HINDSIGHT_URL_ENV = "HINDSIGHT_URL"
HINDSIGHT_TENANT_ENV = "HINDSIGHT_TENANT"

ENTRA_TENANT_ID_ENV = "ENTRA_TENANT_ID"
ENTRA_CLIENT_ID_ENV = "ENTRA_CLIENT_ID"
ENTRA_AUDIENCE_ENV = "ENTRA_AUDIENCE"

# Scheduled protection reads these by name from suite.env.  Keeping the names
# here gives the CLI and the generated OS units one contract without putting a
# DSN value (or a platform-specific path) in either artifact.
SCHEDULE_BACKUP_DIR_ENV = "AGENT_SUITE_BACKUP_DIR"
SCHEDULE_VERIFY_RESTORE_DSN_ENV = "AGENT_SUITE_VERIFY_RESTORE_DSN"


_CONNINFO_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _parse_conninfo_keywords(dsn: str) -> dict[str, str] | None:
    """Parse a libpq keyword/value conninfo string into a key→value dict.

    Implements the libpq grammar subset that matters for identity: ``key =
    value`` pairs separated by whitespace, values optionally single-quoted
    with ``\\'`` and ``\\\\`` escapes. Returns ``None`` on any anomaly (a
    stray token, an unterminated quote) rather than guessing — the caller
    falls back to conservative string comparison.
    """
    result: dict[str, str] = {}
    i, n = 0, len(dsn)
    while i < n:
        while i < n and dsn[i].isspace():
            i += 1
        if i >= n:
            break
        matched = _CONNINFO_KEY_RE.match(dsn, i)
        if matched is None:
            return None
        key = matched.group(0).lower()
        i = matched.end()
        while i < n and dsn[i].isspace():
            i += 1
        if i >= n or dsn[i] != "=":
            return None
        i += 1
        while i < n and dsn[i].isspace():
            i += 1
        if i < n and dsn[i] == "'":
            i += 1
            chars: list[str] = []
            closed = False
            while i < n:
                ch = dsn[i]
                if ch == "\\" and i + 1 < n:
                    chars.append(dsn[i + 1])
                    i += 2
                    continue
                if ch == "'":
                    closed = True
                    i += 1
                    break
                chars.append(ch)
                i += 1
            if not closed:
                return None
            value = "".join(chars)
        else:
            start = i
            while i < n and not dsn[i].isspace():
                i += 1
            value = dsn[start:i]
        result[key] = value
    return result or None


def _keyword_value_identity(dsn: str) -> tuple[str, str, int, str] | None:
    """Database identity of a libpq keyword/value DSN (``host=… dbname=…``).

    ``backup.py`` accepts this DSN spelling, so a keyword-spelled production
    DSN is a real operator shape — comparing it to a URI-spelled scratch DSN
    by raw string only would let the weekly restore point at production
    (WI-071 M1). Multi-host values and nested ``dbname`` conninfo expansion
    are outside the supported subset and return ``None``.
    """
    keywords = _parse_conninfo_keywords(dsn)
    if keywords is None:
        return None
    database = keywords.get("dbname", "")
    if not database or "=" in database:
        return None
    host = keywords.get("host") or keywords.get("hostaddr") or ""
    if "," in host:
        return None
    host = host.strip().lower().rstrip(".")
    raw_port = keywords.get("port", "5432")
    if "," in raw_port:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        return None
    return ("postgresql", host, port, database)


def _postgres_database_identity(dsn: str) -> tuple[str, str, int, str] | None:
    """Return the database target from a supported PostgreSQL DSN.

    Credentials and URI query options are deliberately excluded: changing a
    password, user, or ``sslmode`` does not point ``pg_restore`` at a different
    database.  Both URI and libpq keyword/value spellings are supported;
    anything outside those subsets returns ``None`` and is compared
    conservatively by :func:`same_postgres_database`.
    """
    try:
        parsed = urlsplit(dsn)
        if parsed.scheme.lower() not in {"postgres", "postgresql"}:
            return _keyword_value_identity(dsn)
        options = parse_qs(parsed.query, keep_blank_values=True)
        host = parsed.hostname
        if host is None:
            host = options.get("host", [""])[0]
        host = unquote(host).strip().lower().rstrip(".")

        port = parsed.port
        if port is None:
            raw_port = options.get("port", ["5432"])[0]
            port = int(raw_port)

        database = unquote(parsed.path.lstrip("/").rstrip("/"))
        if not database:
            database = unquote(options.get("dbname", [""])[0])
        if not database:
            return None
        return ("postgresql", host, port, database)
    except (ValueError, UnicodeError):
        return None


def same_postgres_database(left: str, right: str) -> bool:
    """Whether two DSNs identify the same PostgreSQL database.

    Supported URI and keyword/value forms are compared by normalized
    scheme/host/port/database, not by their raw spelling.  If either value is
    outside those supported subsets (multi-host lists, nested ``dbname``
    expansion, service files), equality remains the safe fallback and no DSN
    value is surfaced — a residual fail-open for exotic spellings, accepted
    and documented in WI-071 M1.
    """
    if left == right:
        return True
    left_identity = _postgres_database_identity(left)
    right_identity = _postgres_database_identity(right)
    return left_identity is not None and left_identity == right_identity


def postgres_database_fingerprint(dsn: str) -> str | None:
    """Return a credential-free stable fingerprint for a PostgreSQL target."""
    identity = _postgres_database_identity(dsn)
    if identity is None:
        return None
    material = "\0".join((identity[0], identity[1], str(identity[2]), identity[3]))
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class MemoryProviderConfig:
    """Memory-provider selection (Plan 012 WI-1.1).

    Injected into ``doctor.aggregate()`` and ``bootstrap.run_bootstrap()``
    so tests can drive the hindsight-unreachable path without setting env vars.
    """

    engine: str = "native"
    hindsight_url: str | None = None
    hindsight_tenant: str = "default"
    endpoint: str | None = None

    @classmethod
    def from_env(cls) -> MemoryProviderConfig:
        d = memory_provider_config()
        raw_url = d["hindsight_url"]
        raw_endpoint = d["endpoint"]
        return cls(
            engine=str(d["engine"]),
            hindsight_url=raw_url if isinstance(raw_url, str) else None,
            hindsight_tenant=str(d["hindsight_tenant"]),
            endpoint=raw_endpoint if isinstance(raw_endpoint, str) else None,
        )


def memory_provider_config() -> dict[str, object]:
    """Read memory-provider selection from env / suite.env.

    Returns a dict with ``engine`` (``"native"`` | ``"hindsight"``),
    ``hindsight_url``, ``hindsight_tenant``, and ``endpoint`` (the URL
    for doctor remote checks, or ``None`` when the engine is native).
    """
    engine = os.environ.get(MEMORY_ENGINE_ENV, "native")
    hindsight_url: str | None = os.environ.get(HINDSIGHT_URL_ENV)
    hindsight_tenant = os.environ.get(HINDSIGHT_TENANT_ENV, "default")
    endpoint: str | None = hindsight_url if engine == "hindsight" else None
    return {
        "engine": engine,
        "hindsight_url": hindsight_url,
        "hindsight_tenant": hindsight_tenant,
        "endpoint": endpoint,
    }


#: Every env var that names a regista project slug, in provisioning order.
#: ``DOSSIER_PROJECTS`` is a comma-separated list; the rest are single slugs.
#: `suite.env.example` ships ``CAIRN_PROJECT=agent_provenance`` — a *different*
#: slug from ``REGISTA_PROJECT`` — and bootstrap provisioned only the latter, so
#: cairn was red after a by-the-book install (WI-042).
PROJECT_SLUG_ENV_VARS: tuple[str, ...] = (
    "REGISTA_PROJECT",
    "CAIRN_PROJECT",
    "AGENT_NOTES_PROJECT",
    "DOSSIER_PROJECTS",
)


def configured_project_slugs(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Every project slug the resolved config names, ordered and deduplicated.

    These are the schemas the host will actually write to, and therefore the
    ones ``bootstrap`` must provision. Reading them from config rather than
    accepting one slug is the difference between "the project I was told about
    works" and "this host works".
    """
    source: Mapping[str, str] = os.environ if env is None else env
    slugs: list[str] = []
    for var in PROJECT_SLUG_ENV_VARS:
        for candidate in source.get(var, "").split(","):
            slug = candidate.strip()
            if slug and slug not in slugs:
                slugs.append(slug)
    return tuple(slugs)


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


@dataclass(frozen=True)
class EntraEnvConfig:
    """Entra configuration loaded from environment variables (Plan 014 WI-3.3).

    When ``is_configured`` is True, the caller can construct an
    ``EntraTokenValidator`` with automatic JWKS key fetching.
    """

    tenant_id: str | None = None
    client_id: str | None = None
    audience: str | None = None
    jwks_url: str | None = None

    @classmethod
    def from_env(cls) -> EntraEnvConfig:
        tenant_id = os.environ.get(ENTRA_TENANT_ID_ENV)
        client_id = os.environ.get(ENTRA_CLIENT_ID_ENV)
        audience = os.environ.get(ENTRA_AUDIENCE_ENV)
        jwks_url: str | None = None
        if tenant_id is not None:
            jwks_url = (
                f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
            )
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            audience=audience,
            jwks_url=jwks_url,
        )

    @property
    def is_configured(self) -> bool:
        """True when all required fields are present."""
        return (
            self.tenant_id is not None
            and self.client_id is not None
            and self.audience is not None
        )

    def to_entra_config(self) -> EntraConfig:
        """Convert to EntraConfig. Raises ValueError if not configured."""
        from agent_suite.entra import EntraConfig

        if not self.is_configured:
            raise ValueError("EntraEnvConfig is not fully configured")
        assert self.tenant_id is not None
        assert self.client_id is not None
        assert self.audience is not None
        issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        return EntraConfig(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            issuer=issuer,
            audience=self.audience,
        )
