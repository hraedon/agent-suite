"""Which secret references this host is actually configured with, and whether
they resolve.

WI-041. `docs/secrets-vault.md` §8 promises that bootstrap step 0 "probes the
resolver. If a ``vault:`` ref cannot be resolved, the bootstrap aborts with a
clear message naming the failing ref — it does not proceed to provision against
an unresolvable secret." It did proceed: the step ran ``regista secrets
--list-providers``, which proves a *provider class is registered in regista's
process*, not that any configured reference resolves. The qualification host's
only ``vault:`` ref was repointed at a path its AppRole is denied — proved 403 —
and step 0 still printed "secret backend reachable".

Three ref-shape traps this estate hit, all of which this module catches
*statically*, before any network call:

1. **The mount.** ``kv/`` on the real Vault, not the ``secret/`` every install
   doc prints. A wrong mount is a 403, not a parse error, so only resolution
   catches that one — hence the resolve step.
2. **The field is the LAST PATH SEGMENT.** ``vault:kv/a/b/field``. The
   ``#field`` suffix every doc printed has never worked, and is worse than a
   clean error: ``vault:kv/a/b/regista#hmac_key`` *parses* to mount ``kv``, path
   ``a/b``, field ``regista#hmac_key`` — a **different, neighbouring secret**.
   On a permissive policy that reads something the operator never named.
3. **``hvac`` must be importable in the resolving component's OWN
   environment.** Each suite CLI is its own uv tool venv; ``vault`` appearing in
   regista's provider list says nothing about cairn's. So the probe reports the
   provider set per component that actually has a ``vault:`` ref configured,
   rather than generalising from one.

Nothing in this module ever handles a resolved secret **value**: ``regista
secrets --ref`` prints the resolved secret to stdout on success, so the probe
consults only the exit code and, on failure, the error envelope. See
:func:`probe_ref_argv`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

#: Reads a ``keys.json`` given its path, or returns ``None`` when it cannot be
#: read. Injectable so the discovery path is testable without a real key file.
KeyFileLoader = Callable[[str], "str | None"]

__all__ = [
    "VAULT_REF_LITERAL_RE",
    "ConfiguredRef",
    "KeyFileLoader",
    "config_problems",
    "discover_refs",
    "probe_ref_argv",
    "ref_static_problem",
    "scheme_of",
]

#: The provider names regista's resolver knows (``regista._secrets``
#: ``_KNOWN_PROVIDER_NAMES``). Note ``azure`` and ``windows`` — not ``akv`` or
#: ``wincred``, which several suite docs print and no resolver accepts.
KNOWN_SCHEMES: frozenset[str] = frozenset(
    {"file", "env", "literal", "vault", "azure", "windows"}
)

#: Env vars belonging to the suite. Only these are scanned, so an unrelated
#: variable that happens to hold a colon cannot become a probe target.
_SUITE_VAR_RE = re.compile(
    r"^(REGISTA|CAIRN|AGENT_NOTES|AGENT_SUITE|DOSSIER|ACB|AGENT_WAKE|HINDSIGHT)_"
)

#: Vars that hold a filesystem path or a connection string, never a ref.
#: ``REGISTA_KEY_PATH`` is the sharpest: it is a path to a ``keys.json`` **file**
#: (``KeySet.__init__`` does ``Path(path).read_text()``), and every install doc
#: prints ``REGISTA_KEY_PATH=vault:…`` as though it were a ref. The refs live
#: *inside* that file, as per-key ``secret_ref`` entries — which is what
#: :func:`discover_refs` reads.
_NON_REF_SUFFIXES = ("_PATH", "_DSN", "_URL", "_DIR", "_FILE")

#: A ``vault:`` literal as it appears in prose or an env file. Used both by the
#: discovery path and by the docs test, so a doc cannot print a shape the
#: resolver rejects (WI-039).
VAULT_REF_LITERAL_RE = re.compile(r"vault:[A-Za-z0-9/._#@:-]+")

#: Which component env var belongs to which CLI, for the per-component provider
#: report. A ref configured for cairn is resolved by *cairn's* interpreter.
_VAR_PREFIX_TO_CLI: tuple[tuple[str, str], ...] = (
    ("REGISTA_", "regista"),
    ("CAIRN_", "cairn"),
    ("AGENT_NOTES_", "agent-notes"),
    ("DOSSIER_", "dossier"),
    ("ACB_", "acb"),
    ("AGENT_WAKE_", "agent-wake"),
)


@dataclass(frozen=True)
class ConfiguredRef:
    """One secret reference this host is configured with.

    ``source`` names *where the ref came from* so the abort message is
    actionable ("REGISTA_KEY_PATH keys.json key 'qual-linux-2026-07'
    secret_ref"), and ``owner_cli`` names the component whose own environment
    has to be able to resolve it.
    """

    ref: str
    source: str
    owner_cli: str

    @property
    def scheme(self) -> str:
        return scheme_of(self.ref)


def scheme_of(ref: str) -> str:
    """The backend scheme of ``ref``, mirroring regista's ``_detect_prefix``."""
    prefix, sep, _rest = ref.partition(":")
    if not sep:
        return "file"
    if prefix in KNOWN_SCHEMES:
        return prefix
    if ref.startswith(("/", "~", ".")):
        return "file"
    return "literal"


def _looks_like_ref(value: str) -> bool:
    prefix, sep, rest = value.partition(":")
    return bool(sep) and prefix in KNOWN_SCHEMES and bool(rest)


def ref_static_problem(ref: str) -> str | None:
    """Why ``ref`` can never resolve, judged without touching any backend.

    Returns ``None`` when the shape is resolvable — which is not a promise that
    it *does* resolve (wrong mount, denied policy, missing field are all
    runtime facts). Static and runtime checks are both needed; neither
    substitutes for the other.
    """
    if not ref:
        return "empty secret reference"
    scheme = scheme_of(ref)
    _prefix, _sep, rest = ref.partition(":")
    if scheme == "vault":
        if "#" in ref:
            return (
                f"vault ref {ref!r} uses '#field'; the field is the LAST PATH "
                f"SEGMENT (vault:mount/path/field). This form does not error "
                f"cleanly — it parses to a different, neighbouring secret"
            )
        if len(rest.split("/")) < 4:
            return (
                f"vault ref {ref!r} has {len(rest.split('/'))} segment(s); "
                f"regista requires mount/path.../field (at least 4)"
            )
    if scheme == "literal":
        return (
            f"{ref!r} has no recognised backend scheme, so it resolves as a "
            f"literal secret value rather than a reference "
            f"(known: {', '.join(sorted(KNOWN_SCHEMES))})"
        )
    return None


def probe_ref_argv(ref: str) -> tuple[str, ...]:
    """The command that proves ``ref`` resolves.

    ``regista secrets --ref`` **prints the resolved secret to stdout** on
    success, so callers must consult the exit code and never echo stdout. The
    global ``--json`` makes the *failure* path emit the CLI-contract error
    envelope, which is safe to read and names the reason.
    """
    return ("regista", "--json", "secrets", "--ref", ref)


def config_problems(env: Mapping[str, str]) -> tuple[str, ...]:
    """Configuration that cannot work, whatever the backend says (WI-039).

    These are not resolution failures — they are variables whose *shape* means
    the value will never reach the resolver at all. They are worth catching in
    step 0 because each one was printed by an install doc, so an operator
    following the runbook arrives here believing a secret is custodied when it
    is not.
    """
    problems: list[str] = []
    key_path = env.get("REGISTA_KEY_PATH", "").strip()
    if key_path and _looks_like_ref(key_path):
        problems.append(
            f"REGISTA_KEY_PATH={key_path.split(':', 1)[0]}:… is a backend ref, but "
            f"REGISTA_KEY_PATH is a path to a keys.json FILE (regista reads it with "
            f"Path.read_text). Backend refs belong inside keys.json as per-key "
            f"'secret_ref' + 'encoding' entries; see docs/secrets-vault.md"
        )
    if env.get("REGISTA_DSN_PASSWORD", "").strip():
        problems.append(
            "REGISTA_DSN_PASSWORD is set but is not in regista's config "
            "vocabulary (regista._config _CANONICAL/_ALIASES) — it is silently "
            "ignored, and the DSN password must be part of REGISTA_DSN"
        )
    return tuple(problems)


def _owner_cli(var: str) -> str:
    for prefix, cli in _VAR_PREFIX_TO_CLI:
        if var.startswith(prefix):
            return cli
    return "regista"


def _key_file_refs(key_path: str, load: KeyFileLoader) -> tuple[ConfiguredRef, ...]:
    """The per-key ``secret_ref`` entries inside a regista ``keys.json``.

    This is the form that actually works for custodied signing keys, and the
    form no install doc shows: the runtime proves it with
    ``key_sources={'…': 'secret_ref:vault'}``.
    """
    import json

    text = load(key_path)
    if text is None:
        return ()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, dict):
        return ()
    keys = data.get("keys")
    if not isinstance(keys, list):
        return ()
    found: list[ConfiguredRef] = []
    for entry in keys:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("secret_ref")
        if isinstance(ref, str) and ref.strip():
            key_id = entry.get("key_id", "?")
            found.append(
                ConfiguredRef(
                    ref=ref.strip(),
                    source=f"REGISTA_KEY_PATH {key_path} key {key_id!r} secret_ref",
                    owner_cli="regista",
                )
            )
    return tuple(found)


def _default_loader(path: str) -> str | None:
    from pathlib import Path

    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def discover_refs(
    env: Mapping[str, str],
    *,
    load_key_file: KeyFileLoader = _default_loader,
) -> tuple[ConfiguredRef, ...]:
    """Every backend secret reference this host's resolved config names.

    Two sources: suite env vars whose value carries a backend scheme, and the
    per-key ``secret_ref`` entries inside the ``keys.json`` that
    ``REGISTA_KEY_PATH`` points at. Ordered and deduplicated so the probe's
    output is stable across runs.
    """
    found: list[ConfiguredRef] = []
    for var in sorted(env):
        value = env[var].strip()
        if not value or not _SUITE_VAR_RE.match(var):
            continue
        if var.endswith(_NON_REF_SUFFIXES):
            continue
        if not _looks_like_ref(value):
            continue
        found.append(ConfiguredRef(ref=value, source=var, owner_cli=_owner_cli(var)))

    key_path = env.get("REGISTA_KEY_PATH", "").strip()
    if key_path and not _looks_like_ref(key_path):
        found.extend(_key_file_refs(key_path, load_key_file))

    seen: set[str] = set()
    unique: list[ConfiguredRef] = []
    for candidate in found:
        if candidate.ref in seen:
            continue
        seen.add(candidate.ref)
        unique.append(candidate)
    return tuple(unique)
