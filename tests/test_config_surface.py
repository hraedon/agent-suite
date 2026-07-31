"""`suite.env.example` must be able to configure the host it claims to (WI-047).

`docs/install-linux.md` §3 calls `suite.env.example` "the canonical placeholder
set". The Linux qualification found a Profile B host could not be configured from
it at all: dossier refused to start on `DOSSIER_SESSION_SECRET` and then wanted
eleven more variables, of which the canonical file mentioned two — both commented
out. `CAIRN_CONTENT_KEY_REF` was absent too, so the documented posture was
plaintext content capture reported as a `warn`.

An agent-suite reflection dated 2026-07-19 had already recorded the same gap and
it never reached the file. A reflection is not a check. These tests are the
check, in the shape of
`test_secret_refs.py::test_every_documented_vault_ref_parses` — the docs asserted
a state nobody verified.

The cross-component test is the one that keeps the declaration honest: wherever
dossier is importable it reads dossier's own config module and requires every
`DOSSIER_*` name to be accounted for. It skips where dossier is absent (matching
`conftest.py`'s `_regista_available` idiom) and is made mandatory by
`INTEROP_REQUIRE_FACES=1`, so a host that has the faces cannot quietly not check.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from agent_suite.config_surface import (
    DOSSIER_VARS_NOT_IN_SUITE_ENV,
    PROFILE_B_CONFIG_SURFACE,
    ConfigNeed,
    ConfigVar,
    need_label,
    vars_for_component,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ENV_EXAMPLE = REPO_ROOT / "suite.env.example"

#: A variable is "covered" when the example file names it as an assignment,
#: commented out or not. A bare mention in prose is not configuration.
_ASSIGNMENT_RE = "^\\s*#?\\s*(?:export\\s+)?{name}="


def _example_text() -> str:
    return SUITE_ENV_EXAMPLE.read_text(encoding="utf-8")


def _covers(text: str, name: str) -> bool:
    return (
        re.search(_ASSIGNMENT_RE.format(name=re.escape(name)), text, re.MULTILINE)
        is not None
    )


# ---------------------------------------------------------------------------
# The unconditional check: the file covers the declaration
# ---------------------------------------------------------------------------


def test_the_declaration_is_not_empty() -> None:
    assert PROFILE_B_CONFIG_SURFACE
    assert vars_for_component("dossier")
    assert vars_for_component("cairn")


@pytest.mark.parametrize(
    "var", PROFILE_B_CONFIG_SURFACE, ids=lambda v: v.name
)
def test_suite_env_example_names_every_declared_variable(var: ConfigVar) -> None:
    """One case per variable, so a failure names the missing one."""
    text = _example_text()
    assert _covers(text, var.name), (
        f"suite.env.example does not name {var.name} "
        f"({var.component}, {need_label(var.need)}): {var.why}"
    )


def test_every_required_variable_is_uncommented_or_says_why_not() -> None:
    """A REQUIRED variable commented out is a placeholder set that cannot be copied.

    The one exception is deliberate and must be argued in the file itself:
    `DOSSIER_SESSION_SECRET` cannot live in a shared `suite.env` (dossier resolves
    no backend ref for it — dossier WI-036 — so it must be a literal in the
    service's own environment). The line is present for discoverability and the
    file says where the value belongs.
    """
    text = _example_text()
    commented: list[str] = []
    for var in PROFILE_B_CONFIG_SURFACE:
        if var.need is not ConfigNeed.REQUIRED:
            continue
        if re.search(
            _ASSIGNMENT_RE.format(name=re.escape(var.name)).replace("#?", "#"),
            text,
            re.MULTILINE,
        ) and not re.search(
            f"^\\s*{re.escape(var.name)}=", text, re.MULTILINE
        ):
            commented.append(var.name)
    # LDAP is required only under DOSSIER_AUTH_BACKEND=ldap, so its block is
    # legitimately commented; the example ships the local backend.
    allowed_commented = {
        v.name for v in PROFILE_B_CONFIG_SURFACE if v.name.startswith("DOSSIER_LDAP_")
    } | {"DOSSIER_SESSION_SECRET"}
    assert set(commented) <= allowed_commented, (
        f"required variables are commented out with no stated reason: "
        f"{sorted(set(commented) - allowed_commented)}"
    )


def test_the_qualification_gap_is_closed() -> None:
    """The exact variables the Linux run had to discover by crashing dossier."""
    text = _example_text()
    discovered_by_crashing = (
        "DOSSIER_SESSION_SECRET",
        "DOSSIER_ENV",
        "DOSSIER_USERS_PATH",
        "DOSSIER_AUTH_BACKEND",
        "DOSSIER_TLS_CERT_PATH",
        "DOSSIER_TLS_KEY_PATH",
        "DOSSIER_SECURE_COOKIES",
        "DOSSIER_REQUIRE_SSL",
        "DOSSIER_PROJECT_ACCESS_MODE",
        "DOSSIER_PROJECT_ACL_PATH",
        "DOSSIER_BOOTSTRAP_ADMINS",
        "DOSSIER_ALLOWED_HOSTS",
        "DOSSIER_PRINCIPAL_KEY_DIR",
        # Absent too, and the reason the documented posture was plaintext.
        "CAIRN_CONTENT_KEY_REF",
    )
    missing = [name for name in discovered_by_crashing if not _covers(text, name)]
    assert missing == []


def test_the_identity_binding_and_signing_posture_are_documented() -> None:
    """dossier PR #12 (WI-035) added both, and both are Profile B requirements.

    A host configured without them is one where the human `accept` — the single
    signature the review gate exists to record — is signed with the shared store
    HMAC key and attributable to anyone holding it.
    """
    text = _example_text()
    assert _covers(text, "DOSSIER_HUMAN_SIGNING")
    assert _covers(text, "DOSSIER_LDAP_PRINCIPAL_ID_ATTR")
    # The local backend binds through a users.json field, not an env var, so the
    # file has to say so or an operator on the local backend has no path at all.
    assert "principal_id" in text
    assert "DOSSIER_USERS_PATH" in text


#: A value that is long and carries no separators an operator would have typed
#: looks like generated key material rather than a placeholder.
_HIGH_ENTROPY_RE = re.compile(r"^[A-Za-z0-9+/=_-]{24,}$")


def test_no_declared_variable_ships_secret_material() -> None:
    """Placeholders only — the file's own first line promises this.

    The block added for WI-047 includes a session secret, an LDAP bind password
    and two notification credentials, so the file now has more places for a real
    value to be pasted by accident than it did.
    """
    text = _example_text()
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if not any(v.name == name for v in PROFILE_B_CONFIG_SURFACE):
            continue
        value = value.strip()
        if not value:
            continue
        # A backend ref or a filesystem path is by construction not a secret.
        if value.startswith(
            ("vault:", "azure:", "windows:", "file:", "env:", "/", "<", "http")
        ):
            continue
        assert not _HIGH_ENTROPY_RE.match(value), (
            f"{name} looks like it carries real material, not a placeholder"
        )


def test_the_session_secret_is_not_given_a_value_in_the_shared_file() -> None:
    """dossier resolves no backend ref for it (WI-036), so it cannot be custodied here.

    Putting the literal in a shared `suite.env` is exactly what the qualification
    had to do to get a green doctor, and it contradicts `bootstrap-contract.md` §2
    ("Secrets are backend refs … never literals in the system file"). The variable
    is named so it is discoverable; the file must say where the value belongs
    instead of holding one.
    """
    text = _example_text()
    assigned = re.search(
        r"^\s*DOSSIER_SESSION_SECRET=(?P<value>.*)$", text, re.MULTILINE
    )
    assert assigned is None, "suite.env.example assigns DOSSIER_SESSION_SECRET a value"
    assert "DOSSIER_SESSION_SECRET" in text
    # And it must point somewhere: an operator who cannot put it here needs to be
    # told where it does go.
    assert "EnvironmentFile" in text or "LoadCredential" in text


# ---------------------------------------------------------------------------
# The cross-component check: the declaration tracks dossier
# ---------------------------------------------------------------------------


#: A DOSSIER_* identifier. The trailing-underscore exclusion drops prose
#: mentions of a *prefix* (dossier's own docstrings say "DOSSIER_LDAP_*").
_DOSSIER_ENV_RE = re.compile(r"\bDOSSIER_(?:[A-Z0-9]+_)*[A-Z0-9]+\b")


def _dossier_config_source() -> str | None:
    """dossier's config module source, or None when dossier is not installed."""
    try:
        import dossier.config as dossier_config
    except ImportError:
        return None
    import inspect

    return inspect.getsource(dossier_config)


def _dossier_package_names() -> set[str] | None:
    """Every ``DOSSIER_*`` name mentioned anywhere in the installed dossier.

    Wider than ``config.py`` on purpose: ``DOSSIER_PROJECTS`` is read by
    ``dossier.cli``, not ``dossier.config``, and it is still a variable a
    Profile B operator must set.
    """
    try:
        import dossier
    except ImportError:
        return None
    root = Path(next(iter(dossier.__path__)))
    names: set[str] = set()
    for path in root.rglob("*.py"):
        names |= set(_DOSSIER_ENV_RE.findall(path.read_text(encoding="utf-8")))
    return names


def _skip_or_fail_without_dossier() -> None:
    if os.environ.get("INTEROP_REQUIRE_FACES") == "1":
        pytest.fail(
            "INTEROP_REQUIRE_FACES=1 is set but dossier is not importable — "
            "the cross-component config check cannot run"
        )
    pytest.skip("dossier is not installed")


def test_the_declaration_accounts_for_every_dossier_config_variable() -> None:
    """Read dossier's own config surface and require every name to be accounted for.

    This is what stops the declaration drifting from the component it describes:
    a variable added to `dossier.config` fails this test on any host with dossier
    installed, and the fix is either to document it in `suite.env.example` or to
    record in `DOSSIER_VARS_NOT_IN_SUITE_ENV` why it is deliberately omitted. "We
    forgot" and "we decided" stay distinguishable — which is precisely what
    WI-047 was: a reflection recorded the gap, nothing enforced it.
    """
    source = _dossier_config_source()
    if source is None:
        _skip_or_fail_without_dossier()
        return

    read_by_dossier = set(_DOSSIER_ENV_RE.findall(source))
    assert read_by_dossier, "found no DOSSIER_* names in dossier.config — update this test"

    declared = {v.name for v in PROFILE_B_CONFIG_SURFACE}
    accounted = declared | set(DOSSIER_VARS_NOT_IN_SUITE_ENV)
    unaccounted = sorted(read_by_dossier - accounted)
    assert unaccounted == [], (
        "dossier reads these variables and agent_suite/config_surface.py neither "
        f"declares nor excuses them: {unaccounted}"
    )


#: Names the declaration carries that a *pre-PR-#12* dossier does not mention.
#: They come from dossier PR #12 (WI-035), which the RC artifacts predate, so an
#: older installed dossier legitimately lacks them. Listing them keeps the
#: reverse check meaningful instead of either failing on version skew or being
#: deleted: anything NOT here that dossier has never heard of is docs noise.
_REQUIRES_DOSSIER_PR12 = frozenset(
    {"DOSSIER_HUMAN_SIGNING", "DOSSIER_LDAP_PRINCIPAL_ID_ATTR"}
)


def test_the_declaration_does_not_invent_dossier_variables() -> None:
    """The other direction: a name dossier has never heard of is noise in the docs.

    Scanned across the whole installed package, because not every variable an
    operator must set is read by ``config.py``.
    """
    names = _dossier_package_names()
    if names is None:
        _skip_or_fail_without_dossier()
        return

    declared_dossier = {
        v.name for v in vars_for_component("dossier") if v.name.startswith("DOSSIER_")
    }
    invented = sorted(declared_dossier - names - _REQUIRES_DOSSIER_PR12)
    assert invented == [], (
        f"config_surface.py declares variables dossier never mentions: {invented}"
    )


def test_excluded_variables_each_carry_a_reason() -> None:
    assert DOSSIER_VARS_NOT_IN_SUITE_ENV
    for name, reason in DOSSIER_VARS_NOT_IN_SUITE_ENV.items():
        assert name.startswith("DOSSIER_")
        assert len(reason) > 20, f"{name}'s exclusion reason is not a reason"


def test_deprecated_aliases_are_not_advertised() -> None:
    """The excluded names must genuinely be absent, not merely undeclared."""
    text = _example_text()
    for name in DOSSIER_VARS_NOT_IN_SUITE_ENV:
        assert not _covers(text, name), (
            f"{name} is excluded as deprecated but suite.env.example sets it"
        )


# ---------------------------------------------------------------------------
# Vault custody: document the AppRole posture without claiming it works
# ---------------------------------------------------------------------------


def test_the_approle_variables_are_documented() -> None:
    """An operator following the docs should be able to reach the AppRole posture.

    The Linux qualification could not: regista's `VaultProvider` reads
    `VAULT_TOKEN` and nothing else (regista WI-221), so the run proceeded behind
    an undocumented shim that minted a token per invocation. regista WI-228 adds
    the login; these are its variable names, verified against that branch.
    """
    text = _example_text()
    for var in vars_for_component("vault-custody"):
        assert _covers(text, var.name), f"suite.env.example does not name {var.name}"


def test_the_file_forms_are_the_ones_shown_uncommented() -> None:
    """`VAULT_SECRET_ID_FILE` over `VAULT_SECRET_ID`: the credential stays out of
    every child process's environment. The example must lead with the safer form."""
    text = _example_text()
    for preferred, inline in (
        ("VAULT_ROLE_ID_FILE", "VAULT_ROLE_ID"),
        ("VAULT_SECRET_ID_FILE", "VAULT_SECRET_ID"),
    ):
        assert re.search(f"^\\s*{preferred}=", text, re.MULTILINE), (
            f"{preferred} is not shown as a live setting"
        )
        assert not re.search(f"^\\s*{inline}=", text, re.MULTILINE), (
            f"{inline} is uncommented; the file form should be the default"
        )


def test_vault_token_is_marked_dev_only_and_not_set() -> None:
    """`docs/secrets-vault.md` §8: a production host operates AppRole-only.

    Leaving `VAULT_TOKEN=` live in the canonical placeholder set would make the
    dev-only method the path of least resistance for every new host.
    """
    text = _example_text()
    assert not re.search(r"^\s*VAULT_TOKEN=", text, re.MULTILINE)
    assert "VAULT_TOKEN" in text
    assert "DEV ONLY" in text or "dev-only" in text


def test_the_pending_status_is_stated_where_the_variables_are_printed() -> None:
    """The honesty requirement, checked.

    Printing WI-228's variables without saying they do not work yet would create
    exactly the defect this lane exists to remove: a document asserting a state
    nobody can reach. Both the example file and the runbook must say so, and both
    must give the operator a way to check for themselves.
    """
    for text, where in (
        (_example_text(), "suite.env.example"),
        (
            (REPO_ROOT / "docs" / "secrets-vault.md").read_text(encoding="utf-8"),
            "docs/secrets-vault.md",
        ),
    ):
        assert "WI-228" in text, f"{where} prints the AppRole vars without naming WI-228"
        assert "custody:vault_auth" in text, (
            f"{where} gives the operator no way to check which method authenticated"
        )
        assert "VAULT_TOKEN and nothing else" in text or "NOTHING ELSE" in text, (
            f"{where} does not state what regista actually supports today"
        )


def test_the_runbook_does_not_rely_on_the_unmerged_strategy_doc() -> None:
    """`docs/secrets-instantiation.md` is not on any main — it is an unmerged PR.

    A runbook that builds on a document nobody has is worse than one that admits a
    gap, so the merged runbook says which one it is.
    """
    docs = REPO_ROOT / "docs"
    assert not (docs / "secrets-instantiation.md").exists(), (
        "secrets-instantiation.md now exists — update this test and the note in "
        "secrets-vault.md §8.1 that calls it unmerged"
    )
    runbook = (docs / "secrets-vault.md").read_text(encoding="utf-8")
    assert "not on any main" in runbook
