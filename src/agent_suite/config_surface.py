"""What each component's config actually requires — declared once, checked.

WI-047. `docs/install-linux.md` §3 calls `suite.env.example` "the canonical
placeholder set". A Profile B host could not be configured from it: dossier
refuses to start without ``DOSSIER_SESSION_SECRET`` and then, in order, needs
``DOSSIER_ENV``, ``DOSSIER_USERS_PATH``, ``DOSSIER_AUTH_BACKEND``,
``DOSSIER_TLS_*`` (or ``DOSSIER_BEHIND_TLS_PROXY``), ``DOSSIER_SECURE_COOKIES``,
``DOSSIER_REQUIRE_SSL``, ``DOSSIER_PROJECT_ACCESS_MODE``,
``DOSSIER_PROJECT_ACL_PATH``, ``DOSSIER_BOOTSTRAP_ADMINS``,
``DOSSIER_ALLOWED_HOSTS`` and ``DOSSIER_PRINCIPAL_KEY_DIR``. The canonical file
mentioned two of them, both commented out.

An agent-suite reflection dated 2026-07-19 recorded the same gap
("the operator needs to set DOSSIER_ENV=prod, DOSSIER_SESSION_SECRET,
DOSSIER_USERS_PATH, DOSSIER_TLS_*") and it never reached the example file. A
reflection is not a check, which is why this module exists: the placeholder set
is now derived from a declaration, and a test asserts the file covers it.

Applying Plan 020's standing question to documentation: `suite.env.example`
*asserted* that it was the canonical placeholder set. Nobody checked. This is the
same shape as ``test_secret_refs.py::test_every_documented_vault_ref_parses``,
which Lane H added after the docs printed eight unresolvable ref literals.

Two layers of checking, both in ``tests/test_config_surface.py``:

1. **Unconditional** — every variable declared here appears in
   `suite.env.example`. Always runs, so CI catches a variable added here and not
   documented there.
2. **Cross-component** — when ``dossier`` is importable, every ``DOSSIER_*`` name
   its ``config`` module reads is either declared here or in
   :data:`DOSSIER_VARS_NOT_IN_SUITE_ENV` with a stated reason. This is what makes
   the declaration track dossier rather than drift from it: a new variable in
   dossier fails the agent-suite suite on any host that has dossier installed.

Sources verified against dossier main (``src/dossier/config.py``
``load_settings`` / ``load_ldap_config``, and ``docs/deploy.md``'s table),
including dossier PR #12 (WI-035), which added the identity binding
(``DOSSIER_LDAP_PRINCIPAL_ID_ATTR``, and a ``principal_id`` field on each user's
entry in ``DOSSIER_USERS_PATH``) and the ``DOSSIER_HUMAN_SIGNING`` posture.

stdlib-only, no imports of any component. ``assert_never`` over the closed enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import assert_never

__all__ = [
    "DOSSIER_VARS_NOT_IN_SUITE_ENV",
    "PROFILE_B_CONFIG_SURFACE",
    "SECRETS_VAULT_SECTIONS_REGISTA_CITES",
    "VAULT_APPROLE_VARS",
    "ConfigNeed",
    "ConfigVar",
    "need_label",
    "vars_for_component",
]


class ConfigNeed(Enum):
    """How badly a component needs a variable.

    ``assert_never`` is used over this enum so a newly added level cannot be
    silently unlabelled.
    """

    #: The component refuses to start (or refuses the operation) without it.
    REQUIRED = "required"
    #: It starts without it, but the resulting posture is one no production
    #: deployment should have — a default that is safe for dev and wrong for prod.
    POSTURE = "posture"
    #: Genuinely optional: a feature that is off until configured.
    OPTIONAL = "optional"


def need_label(need: ConfigNeed) -> str:
    match need:
        case ConfigNeed.REQUIRED:
            return "required — the component will not start without it"
        case ConfigNeed.POSTURE:
            return "posture — it starts, but not in a state to deploy"
        case ConfigNeed.OPTIONAL:
            return "optional — a feature that stays off until set"
        case other:
            assert_never(other)


@dataclass(frozen=True)
class ConfigVar:
    """One environment variable a component reads, and why it matters."""

    name: str
    component: str
    need: ConfigNeed
    why: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "component": self.component,
            "need": self.need.value,
            "why": self.why,
        }


#: Every variable a Profile B host must be able to configure from
#: `suite.env.example`. Ordered as an operator meets them.
PROFILE_B_CONFIG_SURFACE: tuple[ConfigVar, ...] = (
    # --- dossier: refuses to start without these -------------------------------
    ConfigVar(
        "DOSSIER_SESSION_SECRET",
        "dossier",
        ConfigNeed.REQUIRED,
        "signed-cookie secret, >= 32 bytes; dossier raises "
        "'DOSSIER_SESSION_SECRET is required' and exits",
    ),
    ConfigVar(
        "DOSSIER_ENV",
        "dossier",
        ConfigNeed.POSTURE,
        "'dev' (default) or 'prod'; prod promotes safe defaults and escalates "
        "the doctor's posture gaps from warn to fail",
    ),
    ConfigVar(
        "DOSSIER_USERS_PATH",
        "dossier",
        ConfigNeed.REQUIRED,
        "JSON users file for the local auth backend; also where each human's "
        "regista principal_id binding lives (dossier WI-035)",
    ),
    ConfigVar(
        "DOSSIER_AUTH_BACKEND",
        "dossier",
        ConfigNeed.POSTURE,
        "'local' (JSON users) or 'ldap' (the workplace directory)",
    ),
    ConfigVar(
        "DOSSIER_PRINCIPAL_KEY_DIR",
        "dossier",
        ConfigNeed.REQUIRED,
        "per-principal key directory; dossier refuses to derive it when "
        "REGISTA_KEY_PATH is a backend ref, because deriving would drop private "
        "keys into the process CWD",
    ),
    ConfigVar(
        "DOSSIER_HUMAN_SIGNING",
        "dossier",
        ConfigNeed.POSTURE,
        "'require' (refuse a human write that could only be signed with the "
        "shared store key — the default in prod) or 'warn'. dossier PR #12 / "
        "WI-035: the qualification's human acceptance was signed with the store "
        "HMAC key, so it was attributable to anyone holding it",
    ),
    # --- dossier: TLS and cookie posture ---------------------------------------
    ConfigVar(
        "DOSSIER_TLS_CERT_PATH",
        "dossier",
        ConfigNeed.POSTURE,
        "set with DOSSIER_TLS_KEY_PATH to serve HTTPS; setting only one is a "
        "fail-loud config error, never a silent plaintext fallback",
    ),
    ConfigVar(
        "DOSSIER_TLS_KEY_PATH",
        "dossier",
        ConfigNeed.POSTURE,
        "the other half of the TLS pair",
    ),
    ConfigVar(
        "DOSSIER_BEHIND_TLS_PROXY",
        "dossier",
        ConfigNeed.POSTURE,
        "'true' when an ingress terminates TLS for dossier — the alternative to "
        "DOSSIER_TLS_*, not an addition to it",
    ),
    ConfigVar(
        "DOSSIER_SECURE_COOKIES",
        "dossier",
        ConfigNeed.POSTURE,
        "'true' for any TLS deploy; 'false' only for local dev over HTTP",
    ),
    ConfigVar(
        "DOSSIER_REQUIRE_SSL",
        "dossier",
        ConfigNeed.POSTURE,
        "governs the *Postgres* connection, not the web listener — a loopback "
        "database with no server cert needs this false even in prod",
    ),
    ConfigVar(
        "DOSSIER_ALLOWED_HOSTS",
        "dossier",
        ConfigNeed.POSTURE,
        "comma-separated Host headers; wires TrustedHostMiddleware only when set",
    ),
    ConfigVar(
        "DOSSIER_SESSION_MAX_AGE_SECONDS",
        "dossier",
        ConfigNeed.OPTIONAL,
        "session lifetime (default 43200); shorten it during a principal_id "
        "changeover so old sessions cannot outlive the binding",
    ),
    # --- dossier: project access (deny-by-default) -----------------------------
    ConfigVar(
        "DOSSIER_PROJECT_ACCESS_MODE",
        "dossier",
        ConfigNeed.POSTURE,
        "'enforce' (the default, deny-by-default), 'audit', or 'open'. Flat-open "
        "is only ever an explicit choice (dossier WI-017)",
    ),
    ConfigVar(
        "DOSSIER_PROJECT_ACL_PATH",
        "dossier",
        ConfigNeed.REQUIRED,
        "the per-project grants enforce/audit read. enforce with no ACL and no "
        "bootstrap admins denies everything — dossier resolves rather than "
        "crashing so the doctor can say so, but nobody can read anything",
    ),
    ConfigVar(
        "DOSSIER_BOOTSTRAP_ADMINS",
        "dossier",
        ConfigNeed.REQUIRED,
        "administrator principals needing no ACL entry — the documented way out "
        "of a locked-out enforce deployment",
    ),
    ConfigVar(
        "DOSSIER_PROJECTS",
        "dossier",
        ConfigNeed.REQUIRED,
        "the regista project slug(s) this dossier fronts",
    ),
    # --- dossier: LDAP (required when DOSSIER_AUTH_BACKEND=ldap) ---------------
    ConfigVar(
        "DOSSIER_LDAP_SERVER",
        "dossier",
        ConfigNeed.REQUIRED,
        "comma-separated ldaps:// URLs; plaintext LDAP is refused outright",
    ),
    ConfigVar(
        "DOSSIER_LDAP_BASE_DN", "dossier", ConfigNeed.REQUIRED, "search base"
    ),
    ConfigVar(
        "DOSSIER_LDAP_BIND_DN", "dossier", ConfigNeed.REQUIRED, "search-then-bind DN"
    ),
    ConfigVar(
        "DOSSIER_LDAP_BIND_PASSWORD",
        "dossier",
        ConfigNeed.REQUIRED,
        "bind credential — a backend ref, never a literal",
    ),
    ConfigVar(
        "DOSSIER_LDAP_DOMAIN",
        "dossier",
        ConfigNeed.REQUIRED,
        "appears in Principal.source as ldap:<domain>",
    ),
    ConfigVar(
        "DOSSIER_LDAP_CA_CERT_FILE",
        "dossier",
        ConfigNeed.REQUIRED,
        "AD root CA PEM; strict mode refuses to fall back to the system trust store",
    ),
    ConfigVar(
        "DOSSIER_LDAP_PRINCIPAL_ID_ATTR",
        "dossier",
        ConfigNeed.REQUIRED,
        "the directory attribute carrying each human's regista principal_id. "
        "Unset means LDAP identities are unbound and their events cannot carry a "
        "per-actor signature (dossier PR #12 / WI-035)",
    ),
    ConfigVar(
        "DOSSIER_LDAP_USER_FILTER",
        "dossier",
        ConfigNeed.OPTIONAL,
        "override the default sAMAccountName filter",
    ),
    ConfigVar(
        "DOSSIER_LDAP_GROUP_STRATEGY",
        "dossier",
        ConfigNeed.OPTIONAL,
        "'direct' (default) or 'nested'",
    ),
    ConfigVar(
        "DOSSIER_LDAP_CONNECT_TIMEOUT",
        "dossier",
        ConfigNeed.OPTIONAL,
        "seconds (default 5)",
    ),
    # --- dossier: notifications ------------------------------------------------
    ConfigVar(
        "DOSSIER_BASE_URL",
        "dossier",
        ConfigNeed.POSTURE,
        "the URL humans are sent; notification links are wrong without it",
    ),
    ConfigVar(
        "DOSSIER_NOTIFICATION_SINK",
        "dossier",
        ConfigNeed.OPTIONAL,
        "where review requests are delivered",
    ),
    ConfigVar(
        "DOSSIER_NOTIFICATION_SECRET_REF",
        "dossier",
        ConfigNeed.OPTIONAL,
        "backend ref for the sink credential",
    ),
    ConfigVar(
        "DOSSIER_NOTIFICATION_SOURCE",
        "dossier",
        ConfigNeed.OPTIONAL,
        "source name on emitted notifications (default 'dossier')",
    ),
    ConfigVar(
        "DOSSIER_NOTIFICATION_IDENTITY",
        "dossier",
        ConfigNeed.OPTIONAL,
        "identity presented to the sink",
    ),
    ConfigVar(
        "DOSSIER_NOTIFICATION_PREF_DIR",
        "dossier",
        ConfigNeed.OPTIONAL,
        "per-principal notification preferences; unset means they do not survive "
        "a restart",
    ),
    ConfigVar(
        "DOSSIER_PROJECT",
        "dossier",
        ConfigNeed.OPTIONAL,
        "single-project alias for DOSSIER_PROJECTS (default 'dossier')",
    ),
    # --- cairn -----------------------------------------------------------------
    ConfigVar(
        "CAIRN_CONTENT_KEY_REF",
        "cairn",
        ConfigNeed.POSTURE,
        "content encryption is ON by default with no key, and cairn's doctor "
        "warns 'Content capture will store plaintext until a key is set' as a "
        "*warn* — so --exit-code stays 0 over a plaintext-by-default posture "
        "(agent-provenance WI-035)",
    ),
    # --- Vault custody: how a host authenticates -------------------------------
    # Not scoped to Profile B, but a Profile B host is where it bites: dossier,
    # cairn, agent-notes and regista each resolve their own refs in their own
    # process, so every one of them needs credentials it can reach.
    ConfigVar(
        "VAULT_ADDR",
        "vault-custody",
        ConfigNeed.REQUIRED,
        "the Vault endpoint; with it unset no vault: ref resolves anywhere",
    ),
    ConfigVar(
        "VAULT_ENV_FILE",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "a mode-0600 env-style plane file holding VAULT_ADDR/VAULT_ROLE_ID/"
        "VAULT_SECRET_ID. acb writes one when it provisions an AppRole, and regista "
        "reads the same names, so one credential file serves both — that interop is "
        "the point of the variable. The process environment wins over the file, and "
        "a named-but-missing file is an error, never a fall-through to ambient "
        "credentials (regista WI-228, acb PR #20)",
    ),
    ConfigVar(
        "VAULT_ROLE_ID_FILE",
        "vault-custody",
        ConfigNeed.POSTURE,
        "a 0600 root-owned file holding the AppRole RoleID — preferred over the "
        "inline form, which lands in every child process's environment",
    ),
    ConfigVar(
        "VAULT_ROLE_ID",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "inline RoleID, where a file is impossible",
    ),
    ConfigVar(
        "VAULT_SECRET_ID_FILE",
        "vault-custody",
        ConfigNeed.POSTURE,
        "a file holding the AppRole SecretID — preferred over inline",
    ),
    ConfigVar(
        "VAULT_SECRET_ID",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "inline SecretID, where a file is impossible",
    ),
    ConfigVar(
        "VAULT_SECRET_ID_RESPONSE_WRAPPED",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "'1' when VAULT_SECRET_ID_FILE holds a response-wrapping token rather "
        "than the SecretID. Delivery is one-shot — the qualification confirmed a "
        "second unwrap returns HTTP 400. Requires VAULT_SECRET_ID_FILE; setting "
        "it inline is an error, not a silent downgrade",
    ),
    ConfigVar(
        "VAULT_APPROLE_MOUNT_POINT",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "the AppRole auth mount (default 'approle')",
    ),
    ConfigVar(
        "VAULT_TOKEN",
        "vault-custody",
        ConfigNeed.OPTIONAL,
        "DEV ONLY — a static token, kept so `vault server -dev` works. A "
        "production host operates AppRole-only with none in its environment. "
        "Setting any AppRole variable means AppRole and this is never consulted "
        "thereafter: there is no fallback, because falling back would turn a "
        "broken production posture into a working dev one silently (regista "
        "WI-228; WI-221 was the pre-AppRole state the qualification hit)",
    ),
)

#: The AppRole variables above are regista WI-228's convention, verified against
#: regista ``origin/main`` ``e32ec9b`` (PR #16) — ``src/regista/_secrets.py``. They
#: are **merged and working**: an earlier revision of this file carried a "not yet
#: on regista main" caveat, which was true when written and false within the hour.
#:
#: Kept as a named set because the cross-repo coupling is real: regista's own error
#: messages and doctor detail cite ``agent-suite docs/secrets-vault.md`` §5 and §6
#: by number, so those section numbers are part of the contract rather than a
#: presentational choice. ``tests/test_config_surface.py`` pins both directions.
VAULT_APPROLE_VARS: frozenset[str] = frozenset(
    {
        "VAULT_ENV_FILE",
        "VAULT_ROLE_ID",
        "VAULT_ROLE_ID_FILE",
        "VAULT_SECRET_ID",
        "VAULT_SECRET_ID_FILE",
        "VAULT_SECRET_ID_RESPONSE_WRAPPED",
        "VAULT_APPROLE_MOUNT_POINT",
    }
)

#: The section numbers regista's merged code cites in operator-facing text. If
#: `secrets-vault.md` renumbers, regista starts pointing operators at the wrong
#: section — the same defect class this lane exists to remove, aimed the other way
#: across the repo boundary.
SECRETS_VAULT_SECTIONS_REGISTA_CITES: dict[str, str] = {
    "5": "SecretID delivery / how resolution works",
    "6": "how each component authenticates — the AppRole posture",
}


#: ``DOSSIER_*`` variables deliberately absent from `suite.env.example`, with the
#: reason. The cross-component test requires every name dossier reads to be
#: either declared above or listed here, so "we forgot" and "we decided" are
#: distinguishable — and neither can happen silently.
DOSSIER_VARS_NOT_IN_SUITE_ENV: dict[str, str] = {
    "DOSSIER_DATABASE_URL": (
        "deprecated alias for REGISTA_DSN; dossier warns when only the alias is "
        "set, and printing it would invite new hosts onto the deprecated name"
    ),
    "DOSSIER_HMAC_KEY_PATH": (
        "deprecated alias for REGISTA_KEY_PATH, same reason"
    ),
}


def vars_for_component(component: str) -> tuple[ConfigVar, ...]:
    """Every declared variable for one component, in declaration order."""
    return tuple(v for v in PROFILE_B_CONFIG_SURFACE if v.component == component)
