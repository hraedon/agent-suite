"""The documented Postgres prerequisites must be sufficient, and must agree (WI-046).

The Linux qualification set a host up exactly per `deployment-guide.md` §2.2 and
then hit:

    $ regista provision --project agent_provenance
    ... all 44 migrations applied ...
    [FAIL] agent_provenance: permission denied to create role
    DETAIL:  Only roles with the CREATEROLE attribute may create roles.
    exit=1

The SQL created the service role with `LOGIN` + `PASSWORD` and database ownership
only. `regista provision` creates a **per-project** service role and needs
`CREATEROLE`. Note the partial application: the schema migrations land, *then* the
role step fails, so the documented prerequisite being wrong leaves a
half-provisioned project rather than a clean refusal.

Two further gaps in the same finding: `deployment-guide.md` §2.1 said "Postgres
15+" while `install-linux.md` §1 said "18+" — an operator following the first can
deploy a host the second calls unsupported — and neither mentioned pgvector,
which agent-notes' `schema/000_core.sql` requires (`CREATE EXTENSION vector`) and
which only a superuser can create.

The prose was corrected in 42079fe. These tests are what makes the correction
hold: they are the `test_secret_refs.py::test_every_documented_vault_ref_parses`
pattern applied to a prerequisite. Nothing in the suite verifies `CREATEROLE`
against a live host (that needs a database connection, which is regista's
concern — see regista WI-230), so the least a machine can do is check that the
documents say something sufficient and say it consistently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_GUIDE = REPO_ROOT / "docs" / "deployment-guide.md"
INSTALL_LINUX = REPO_ROOT / "docs" / "install-linux.md"
SUPPORT_MATRIX = REPO_ROOT / "data" / "support-matrix.json"

#: Every document that states a Postgres requirement to an operator.
_PREREQ_DOCS = (DEPLOYMENT_GUIDE, INSTALL_LINUX)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _matrix_postgres_major() -> str:
    matrix = json.loads(_text(SUPPORT_MATRIX))
    return str(matrix["postgres_version"]).rstrip("+")


# ---------------------------------------------------------------------------
# The version floor: one number, everywhere
# ---------------------------------------------------------------------------

#: Any statement of a Postgres major-version floor an operator would read as
#: normative. Deliberately broad — it must catch both prose ("Postgres 18+") and
#: a requirements table row ("| Postgres | 18+ …"), because the defect was two
#: documents each stating a *different* floor in a different shape, and each
#: individually looked fine.
_POSTGRES_FLOOR_RE = re.compile(r"Postgres[^\d\n]{0,12}(\d+)\+", re.IGNORECASE)


@pytest.mark.parametrize("doc", _PREREQ_DOCS, ids=lambda p: p.name)
def test_no_document_states_a_postgres_floor_other_than_the_matrix(doc: Path) -> None:
    """The 15-vs-18 disagreement, pinned.

    ``test_support_matrix.py`` already asserted install docs *mention* the matrix
    version — which "Postgres 18+" satisfied while `deployment-guide.md` said 15+
    a few lines away in a document that test did not read at all. Presence is not
    agreement.
    """
    expected = _matrix_postgres_major()
    floors = set(_POSTGRES_FLOOR_RE.findall(_text(doc)))
    assert floors, f"{doc.name} states no Postgres floor at all"
    assert floors == {expected}, (
        f"{doc.name} states Postgres floor(s) {sorted(floors)}; the support "
        f"matrix says {expected}+. An operator following the lower number "
        f"deploys a host the other document calls unsupported."
    )


def test_the_two_guides_state_the_same_floor() -> None:
    """Stated directly, because it is the actual failure mode."""
    floors = {
        doc.name: set(_POSTGRES_FLOOR_RE.findall(_text(doc))) for doc in _PREREQ_DOCS
    }
    distinct = set().union(*floors.values())
    assert len(distinct) == 1, f"the guides disagree on the Postgres floor: {floors}"


# ---------------------------------------------------------------------------
# CREATEROLE: the prerequisite that was actually insufficient
# ---------------------------------------------------------------------------

#: The `CREATE ROLE` statement the guide tells an operator to run for the regista
#: service role — the one `regista provision` connects as.
_CREATE_SERVICE_ROLE_RE = re.compile(
    r'^CREATE ROLE "DB-SERVICE-ACCOUNT"\s+WITH\s+(?P<attrs>[^;]*);', re.MULTILINE
)


def test_the_documented_create_role_grants_createrole() -> None:
    """`regista provision` creates a per-project role; without this it cannot.

    This is the whole of WI-046(a). The statement shipped as
    ``CREATE ROLE ... WITH LOGIN PASSWORD '...'``, which produces a role that
    applies 44 migrations and then cannot finish provisioning.
    """
    match = _CREATE_SERVICE_ROLE_RE.search(_text(DEPLOYMENT_GUIDE))
    assert match is not None, (
        "deployment-guide.md no longer contains the documented CREATE ROLE for "
        "the regista service account — update this test with the new shape"
    )
    attrs = match.group("attrs").upper()
    assert "CREATEROLE" in attrs, (
        "the documented CREATE ROLE omits CREATEROLE, so a host built from this "
        "guide cannot complete `regista provision` (WI-046)"
    )
    assert "LOGIN" in attrs, "the service role still needs LOGIN"


def test_both_guides_name_createrole_as_a_prerequisite() -> None:
    """An operator reading either document must learn this, not just the SQL block."""
    for doc in _PREREQ_DOCS:
        assert "CREATEROLE" in _text(doc), f"{doc.name} does not mention CREATEROLE"


def test_the_guide_gives_the_in_place_remedy() -> None:
    """Most hosts have an existing role, so `ALTER ROLE` is the common path."""
    text = _text(DEPLOYMENT_GUIDE)
    assert re.search(r"ALTER ROLE\s+\"DB-SERVICE-ACCOUNT\"\s+WITH\s+CREATEROLE", text)


def test_the_guide_names_the_half_provisioned_recovery() -> None:
    """The failure is not clean, so the remedy must cover the state it leaves.

    Migrations land and *then* the role step fails. An operator who fixes only the
    grant needs to be told that re-running `regista provision` is safe — otherwise
    the reasonable guess is that a half-provisioned schema must be torn down.
    Same convention as 99df507: a report, or a runbook, names its remedy.
    """
    text = _text(DEPLOYMENT_GUIDE)
    assert "half-provisioned" in text
    assert "idempotent" in text
    assert "regista provision --project" in text


def test_the_guides_admit_the_suite_does_not_verify_this() -> None:
    """Plan 020's standing question, answered out loud.

    `bootstrap`'s `probe_db` step establishes reachability — presence, not
    capability — so the prerequisite is documented and unverified. Saying so, and
    giving the operator the check, is honest; implying bootstrap will catch it is
    not.
    """
    guide = _text(DEPLOYMENT_GUIDE)
    assert "rolcreaterole" in guide, (
        "the guide does not give the operator a way to check CREATEROLE"
    )
    assert "reachable" in guide
    for doc in _PREREQ_DOCS:
        assert "§2.2.1" in _text(doc) or "2.2.1" in _text(doc), (
            f"{doc.name} does not point at the pre-bootstrap verification steps"
        )


# ---------------------------------------------------------------------------
# pgvector: a hard prerequisite neither guide used to mention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc", _PREREQ_DOCS, ids=lambda p: p.name)
def test_pgvector_is_documented_as_a_prerequisite(doc: Path) -> None:
    """agent-notes' `schema/000_core.sql` does `CREATE EXTENSION vector`.

    Without it the projection migration fails, and an extension can only be
    created by a superuser — so this is not something the service role can fix
    later.
    """
    text = _text(doc)
    assert "pgvector" in text, f"{doc.name} does not mention pgvector"
    assert "superuser" in text, (
        f"{doc.name} mentions pgvector but not that a superuser must create it"
    )


def test_the_guide_gives_the_create_extension_step() -> None:
    text = _text(DEPLOYMENT_GUIDE)
    assert re.search(
        r"CREATE EXTENSION IF NOT EXISTS vector", text, re.IGNORECASE
    ), "deployment-guide.md does not give the CREATE EXTENSION step"
    # In the agent-notes database, not the regista one.
    assert "agent_notes" in text
