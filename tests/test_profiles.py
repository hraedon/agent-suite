from __future__ import annotations

import pytest

from agent_suite.components import COMPONENTS
from agent_suite.profiles import (
    FEATURE_MATRIX,
    PROFILE_DESCRIPTIONS,
    PROFILE_REQUIREMENTS,
    Maturity,
    Profile,
    ProfileClassification,
    classify_doctor,
    maturity_label,
    profile_for_components,
    profile_label,
)

_ALL_IDENTS = {c.ident for c in COMPONENTS}
_A_IDENTS = {"regista", "agent-notes", "agent-provenance"}
_B_IDENTS = {"regista", "agent-notes", "agent-provenance", "dossier"}
_C_IDENTS = _ALL_IDENTS


# --- profile_for_components --------------------------------------------------


def test_profile_for_components_full_suite_is_c() -> None:
    assert profile_for_components(_ALL_IDENTS) is Profile.C


def test_profile_for_components_profile_a_exact() -> None:
    assert profile_for_components(_A_IDENTS) is Profile.A


def test_profile_for_components_profile_b_exact() -> None:
    assert profile_for_components(_B_IDENTS) is Profile.B


def test_profile_for_components_profile_c_exact() -> None:
    assert profile_for_components(_C_IDENTS) is Profile.C


def test_profile_for_components_below_a_is_none() -> None:
    assert profile_for_components({"regista", "agent-notes"}) is None


def test_profile_for_components_empty_is_none() -> None:
    assert profile_for_components(set()) is None


def test_profile_for_components_extra_optional_does_not_bump_profile() -> None:
    installed = {"regista", "agent-notes", "agent-provenance", "agent-wake"}
    assert profile_for_components(installed) is Profile.A


def test_profile_for_components_superset_still_highest() -> None:
    installed = _B_IDENTS | {"agent-capability-broker"}
    assert profile_for_components(installed) is Profile.B


# --- classify_doctor ---------------------------------------------------------


def _statuses(installed: set[str], absent: set[str]) -> dict[str, str]:
    return {ident: "ok" for ident in installed} | {
        ident: "absent" for ident in absent
    }


def test_classify_doctor_full_suite() -> None:
    cls = classify_doctor({ident: "ok" for ident in _ALL_IDENTS})
    assert cls.profile is Profile.C
    assert cls.missing_required == []
    assert cls.extra_optional == []


def test_classify_doctor_profile_a_exact() -> None:
    absent = _ALL_IDENTS - _A_IDENTS
    cls = classify_doctor(_statuses(_A_IDENTS, absent))
    assert cls.profile is Profile.A
    assert cls.missing_required == []
    assert cls.extra_optional == []


def test_classify_doctor_profile_b_with_extra_optional() -> None:
    installed = _B_IDENTS | {"agent-wake"}
    absent = _ALL_IDENTS - installed
    cls = classify_doctor(_statuses(installed, absent))
    assert cls.profile is Profile.B
    assert cls.missing_required == []
    assert cls.extra_optional == ["agent-wake"]


def test_classify_doctor_below_a_shows_missing_and_extra() -> None:
    installed = {"regista", "agent-notes", "dossier"}
    absent = _ALL_IDENTS - installed
    cls = classify_doctor(_statuses(installed, absent))
    assert cls.profile is None
    assert cls.missing_required == ["agent-provenance"]
    assert cls.extra_optional == ["dossier"]


def test_classify_doctor_all_absent() -> None:
    cls = classify_doctor({ident: "absent" for ident in _ALL_IDENTS})
    assert cls.profile is None
    assert sorted(cls.missing_required) == ["agent-notes", "agent-provenance", "regista"]
    assert cls.extra_optional == []


def test_classify_doctor_empty_dict() -> None:
    cls = classify_doctor({})
    assert cls.profile is None
    assert sorted(cls.missing_required) == ["agent-notes", "agent-provenance", "regista"]
    assert cls.extra_optional == []


def test_classify_doctor_treats_non_absent_as_installed() -> None:
    statuses = {
        "regista": "degraded",
        "agent-notes": "failed",
        "agent-provenance": "ok",
        "dossier": "absent",
        "agent-capability-broker": "absent",
        "agent-wake": "absent",
    }
    cls = classify_doctor(statuses)
    assert cls.profile is Profile.A


def test_classify_doctor_returns_frozen_dataclass() -> None:
    cls = classify_doctor({})
    with pytest.raises(Exception):
        cls.profile = Profile.A  # type: ignore[misc]


# --- FEATURE_MATRIX component idents -----------------------------------------


def test_feature_matrix_providing_components_are_valid() -> None:
    valid_idents = {c.ident for c in COMPONENTS} | {"agent-suite"}
    for feature in FEATURE_MATRIX:
        for comp in feature.providing_components:
            assert comp in valid_idents, (
                f"feature {feature.name!r} references unknown component {comp!r}"
            )


def test_feature_matrix_has_at_least_ten_entries() -> None:
    assert len(FEATURE_MATRIX) >= 10


def test_feature_matrix_profiles_are_valid_enums() -> None:
    for feature in FEATURE_MATRIX:
        for p in feature.profiles:
            assert isinstance(p, Profile)


def test_feature_matrix_maturity_is_valid_enum() -> None:
    for feature in FEATURE_MATRIX:
        assert isinstance(feature.maturity, Maturity)


def test_feature_matrix_names_are_unique() -> None:
    names = [f.name for f in FEATURE_MATRIX]
    assert len(names) == len(set(names))


# --- PROFILE_REQUIREMENTS superset chain -------------------------------------


def test_profile_requirements_b_superset_a() -> None:
    assert PROFILE_REQUIREMENTS[Profile.A] <= PROFILE_REQUIREMENTS[Profile.B]


def test_profile_requirements_c_superset_b() -> None:
    assert PROFILE_REQUIREMENTS[Profile.B] <= PROFILE_REQUIREMENTS[Profile.C]


def test_profile_requirements_strictly_growing() -> None:
    assert len(PROFILE_REQUIREMENTS[Profile.A]) < len(PROFILE_REQUIREMENTS[Profile.B])
    assert len(PROFILE_REQUIREMENTS[Profile.B]) < len(PROFILE_REQUIREMENTS[Profile.C])


def test_profile_requirements_a_components_match_components_py() -> None:
    expected = {"regista", "agent-notes", "agent-provenance"}
    assert PROFILE_REQUIREMENTS[Profile.A] == expected


def test_profile_requirements_c_is_all_six_components() -> None:
    assert PROFILE_REQUIREMENTS[Profile.C] == _ALL_IDENTS


# --- enum exhaustiveness (assert_never dispatch) -----------------------------


@pytest.mark.parametrize("profile", list(Profile))
def test_profile_label_is_total(profile: Profile) -> None:
    assert isinstance(profile_label(profile), str)


@pytest.mark.parametrize("maturity", list(Maturity))
def test_maturity_label_is_total(maturity: Maturity) -> None:
    assert isinstance(maturity_label(maturity), str)


# --- PROFILE_DESCRIPTIONS ----------------------------------------------------


def test_profile_descriptions_cover_all_profiles() -> None:
    for profile in Profile:
        assert profile in PROFILE_DESCRIPTIONS
        assert len(PROFILE_DESCRIPTIONS[profile]) > 0


# --- ProfileClassification.to_dict -------------------------------------------


def test_profile_classification_to_dict_with_profile() -> None:
    cls = ProfileClassification(
        profile=Profile.B,
        missing_required=[],
        extra_optional=["agent-wake"],
    )
    d = cls.to_dict()
    assert d["profile"] == "B"
    assert d["missing_required"] == []
    assert d["extra_optional"] == ["agent-wake"]


def test_profile_classification_to_dict_without_profile() -> None:
    cls = ProfileClassification(
        profile=None,
        missing_required=["agent-provenance"],
        extra_optional=[],
    )
    d = cls.to_dict()
    assert d["profile"] is None
    assert d["missing_required"] == ["agent-provenance"]
    assert d["extra_optional"] == []


def test_profile_classification_to_dict_copies_lists() -> None:
    cls = ProfileClassification(
        profile=Profile.A,
        missing_required=["x"],
        extra_optional=["y"],
    )
    d = cls.to_dict()
    missing = d["missing_required"]
    assert isinstance(missing, list)
    missing.append("z")
    assert "z" not in cls.missing_required
