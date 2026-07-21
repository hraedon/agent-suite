"""Cross-repo lock-agreement check (Plan 019 B2-generalize).

Unit tests for the pure agreement logic. The integration path (real siblings
checked out at umbrella-pinned revisions) runs in the `feature-probes` CI job
via `scripts/check-lock-agreement.py`; here we exercise the logic with fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_suite.lock_agreement import (
    AgreementStatus,
    check_all,
    check_member,
    has_disagreement,
    spine_from_text,
    umbrella_regista_pin,
)

_UMBRELLA = """
[suite]
release = "1.0.0-dev"

[components.regista]
repo = "hraedon/regista"
version = "0.5.3"
revision = "9718b941939884fee94c260f19efe3e4040c456b"

[components.dossier]
repo = "hraedon/dossier"
version = "0.0.1"
revision = "ed7828d715c3bcd257b625f059ccbed14cf9d815"
"""

# A face-local lock that AGREES with the umbrella regista pin.
_SPINE_AGREE = """
[component]
name = "dossier"
version = "0.0.1"

[spine]
name = "regista"
distribution = "regista-hraedon"
version = "0.5.3"
sha = "9718b941939884fee94c260f19efe3e4040c456b"
describe = "v0.5.3"
"""

_SPINE_BAD_VERSION = _SPINE_AGREE.replace('version = "0.5.3"', 'version = "0.5.1"')
_SPINE_BAD_SHA = _SPINE_AGREE.replace(
    "9718b941939884fee94c260f19efe3e4040c456b",
    "0000000000000000000000000000000000000000",
)
_NO_SPINE = '[component]\nname = "agent-wake"\nversion = "0.1.0"\n'


def test_umbrella_regista_pin_extracts_version_and_revision():
    version, revision = umbrella_regista_pin(_UMBRELLA)
    assert version == "0.5.3"
    assert revision == "9718b941939884fee94c260f19efe3e4040c456b"


def test_umbrella_pin_missing_regista_raises():
    with pytest.raises(ValueError):
        umbrella_regista_pin('[suite]\nrelease = "x"\n')


def test_spine_from_text_present_and_absent():
    assert spine_from_text(_SPINE_AGREE) == (
        "0.5.3",
        "9718b941939884fee94c260f19efe3e4040c456b",
    )
    assert spine_from_text(_NO_SPINE) is None


def test_check_member_agree():
    r = check_member(
        "dossier", "0.5.3", "9718b941939884fee94c260f19efe3e4040c456b", _SPINE_AGREE
    )
    assert r.status is AgreementStatus.AGREE


def test_check_member_disagree_on_version():
    r = check_member(
        "dossier", "0.5.3", "9718b941939884fee94c260f19efe3e4040c456b", _SPINE_BAD_VERSION
    )
    assert r.status is AgreementStatus.DISAGREE
    assert "version" in r.detail


def test_check_member_disagree_on_sha():
    r = check_member(
        "dossier", "0.5.3", "9718b941939884fee94c260f19efe3e4040c456b", _SPINE_BAD_SHA
    )
    assert r.status is AgreementStatus.DISAGREE
    assert "sha" in r.detail


def test_check_member_no_spine_is_not_a_failure():
    assert (
        check_member("agent-wake", "0.5.3", "abc", _NO_SPINE).status
        is AgreementStatus.NO_SPINE
    )
    assert (
        check_member("agent-wake", "0.5.3", "abc", None).status
        is AgreementStatus.NO_SPINE
    )


def test_check_all_skips_the_spine_and_sorts():
    results = check_all(
        _UMBRELLA,
        {
            "regista": "irrelevant",  # the spine — never checked against itself
            "dossier": _SPINE_AGREE,
            "agent-wake": _NO_SPINE,
        },
    )
    members = [r.member for r in results]
    assert "regista" not in members
    assert members == sorted(members)
    assert not has_disagreement(results)


def test_check_all_flags_a_drifted_member():
    results = check_all(_UMBRELLA, {"dossier": _SPINE_BAD_VERSION})
    assert has_disagreement(results)


def test_committed_umbrella_lock_has_a_regista_pin():
    """The real umbrella SUITE.lock must carry a well-formed regista pin."""
    lock_path = Path(__file__).resolve().parent.parent / "SUITE.lock"
    version, revision = umbrella_regista_pin(lock_path.read_text(encoding="utf-8"))
    assert version
    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
