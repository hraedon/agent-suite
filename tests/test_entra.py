from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agent_suite.dual_control import StepUpLevel
from agent_suite.entra import EntraConfig, EntraError, EntraTokenValidator


def _config() -> EntraConfig:
    return EntraConfig(
        tenant_id="tenant-id-placeholder",
        client_id="client-id-placeholder",
        issuer="https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        audience="client-id-placeholder",
    )


class _MockJWT:
    @staticmethod
    def decode(token: str, **kwargs: object) -> dict[str, object]:
        import base64
        import json

        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("invalid token")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))


def _make_jwt(payload: dict[str, object]) -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}."


def test_entra_module_imports_without_pyjwt() -> None:
    from agent_suite import entra

    assert hasattr(entra, "EntraTokenValidator")


def test_validate_fails_closed_without_signing_key() -> None:
    validator = EntraTokenValidator(_config())
    with pytest.raises(EntraError, match="no signing key"):
        validator.validate("dummy-token", StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_missing_pyjwt() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    with patch.dict("sys.modules", {"jwt": None}):
        with pytest.raises(EntraError, match="PyJWT not installed"):
            validator.validate("dummy-token", StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_expired_token() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) - 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="expired"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_missing_principal() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="principal"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_acr_mismatch() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:1f:singlefactor",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="step-up"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_unrecognized_acr() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "unknown-acr-value",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="unrecognized acr"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_accepts_higher_level_token() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:3f:hardtoken",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        result = validator.validate(token, StepUpLevel.MULTI_FACTOR)
    assert result.principal_id == "user-001"
    assert result.step_up_level is StepUpLevel.HARD_TOKEN


def test_validate_returns_validated_token_on_success() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        result = validator.validate(token, StepUpLevel.MULTI_FACTOR)
    assert result.principal_id == "user-001"
    assert result.step_up_level is StepUpLevel.MULTI_FACTOR
    assert result.token_hash.startswith("sha256:")


def test_validate_raises_on_tenant_mismatch() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "wrong-tenant",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="tenant"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_invalid_exp() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": "not-a-number",
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="exp"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)
