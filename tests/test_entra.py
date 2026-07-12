from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agent_suite.config import EntraEnvConfig
from agent_suite.dual_control import StepUpLevel, ValidatedToken
from agent_suite.entra import (
    EntraConfig,
    EntraError,
    EntraTokenValidator,
    TokenCache,
    default_jwks_url,
)


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


def test_validate_raises_on_missing_tid() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="tid"):
            validator.validate(token, StepUpLevel.MULTI_FACTOR)


def test_validate_raises_on_malformed_nbf() -> None:
    validator = EntraTokenValidator(_config(), signing_key="fake-key")
    token = _make_jwt({
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "nbf": "not-a-number",
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    })
    with patch.dict("sys.modules", {"jwt": _MockJWT()}):
        with pytest.raises(EntraError, match="invalid nbf"):
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


# ---------------------------------------------------------------------------
# JWKS mock helpers
# ---------------------------------------------------------------------------


class _MockJWK:
    def __init__(self) -> None:
        self.key = "mock-jwks-key"


class _MockJWKClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.fetch_calls: list[str] = []

    def get_signing_key_from_jwt(self, token: str) -> _MockJWK:
        self.fetch_calls.append(token)
        return _MockJWK()


class _MockJWTJWKS:
    """Mock jwt module with PyJWKClient support."""

    PyJWKClient = _MockJWKClient

    @staticmethod
    def decode(token: str, **kwargs: object) -> dict[str, object]:
        import base64
        import json

        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("invalid token")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))


def _valid_token_payload() -> dict[str, object]:
    return {
        "oid": "user-001",
        "exp": int(time.time()) + 3600,
        "acr": "urn:microsoft:entra:2f:mfa",
        "aud": "client-id-placeholder",
        "iss": "https://login.microsoftonline.com/tenant-id-placeholder/v2.0",
        "tid": "tenant-id-placeholder",
    }


# ---------------------------------------------------------------------------
# WI-3.1 — JWKS key fetching
# ---------------------------------------------------------------------------


def test_default_jwks_url() -> None:
    config = _config()
    url = default_jwks_url(config)
    assert url == (
        "https://login.microsoftonline.com/tenant-id-placeholder/discovery/v2.0/keys"
    )


def test_validate_with_jwks_url_uses_client() -> None:
    validator = EntraTokenValidator(_config(), jwks_url=default_jwks_url(_config()))
    token = _make_jwt(_valid_token_payload())
    with patch.dict("sys.modules", {"jwt": _MockJWTJWKS()}):
        result = validator.validate(token, StepUpLevel.MULTI_FACTOR)
    assert result.principal_id == "user-001"
    client = validator._jwks_client
    assert client is not None
    assert len(client.fetch_calls) == 1


def test_validate_with_jwks_url_caches_client() -> None:
    validator = EntraTokenValidator(_config(), jwks_url=default_jwks_url(_config()))
    token = _make_jwt(_valid_token_payload())
    with patch.dict("sys.modules", {"jwt": _MockJWTJWKS()}):
        validator.validate(token, StepUpLevel.MULTI_FACTOR)
        client1 = validator._jwks_client
        validator.validate(token, StepUpLevel.MULTI_FACTOR)
        client2 = validator._jwks_client
    assert client1 is not None
    assert client1 is client2


def test_validate_with_jwks_url_refreshes_after_ttl() -> None:
    validator = EntraTokenValidator(
        _config(), jwks_url=default_jwks_url(_config()), _jwks_cache_ttl=0.0,
    )
    token = _make_jwt(_valid_token_payload())
    with patch.dict("sys.modules", {"jwt": _MockJWTJWKS()}):
        validator.validate(token, StepUpLevel.MULTI_FACTOR)
        client1 = validator._jwks_client
        validator.validate(token, StepUpLevel.MULTI_FACTOR)
        client2 = validator._jwks_client
    assert client1 is not None
    assert client2 is not None
    assert client1 is not client2


def test_jwks_url_fails_closed_without_pyjwt() -> None:
    validator = EntraTokenValidator(_config(), jwks_url=default_jwks_url(_config()))
    with patch.dict("sys.modules", {"jwt": None}):
        with pytest.raises(EntraError, match="PyJWT not installed"):
            validator.validate("dummy-token", StepUpLevel.MULTI_FACTOR)


# ---------------------------------------------------------------------------
# WI-3.2 — TokenCache
# ---------------------------------------------------------------------------


def _make_validated_token(
    *,
    token_hash: str = "sha256:test",
    principal_id: str = "user-001",
    expires_at: float | None = None,
) -> ValidatedToken:
    now = time.time()
    return ValidatedToken(
        principal_id=principal_id,
        step_up_level=StepUpLevel.MULTI_FACTOR,
        validated_at=now,
        expires_at=expires_at if expires_at is not None else now + 3600,
        token_hash=token_hash,
    )


def test_token_cache_get_returns_none_for_missing() -> None:
    cache = TokenCache()
    assert cache.get("sha256:nonexistent") is None


def test_token_cache_put_and_get() -> None:
    cache = TokenCache()
    token = _make_validated_token(token_hash="sha256:abc")
    cache.put(token)
    result = cache.get("sha256:abc")
    assert result is not None
    assert result.principal_id == "user-001"


def test_token_cache_evicts_expired() -> None:
    cache = TokenCache()
    now = time.time()
    token = _make_validated_token(
        token_hash="sha256:expired",
        expires_at=now - 100,
    )
    cache.put(token)
    assert cache.get("sha256:expired") is None


def test_token_cache_cleanup_returns_count() -> None:
    cache = TokenCache()
    now = time.time()
    token1 = _make_validated_token(token_hash="sha256:t1", expires_at=now + 100)
    token2 = _make_validated_token(token_hash="sha256:t2", expires_at=now + 100)
    cache.put(token1)
    cache.put(token2)
    with patch("time.time", return_value=now + 200):
        removed = cache.cleanup()
    assert removed == 2


def test_token_cache_max_entries() -> None:
    cache = TokenCache(max_entries=2)
    now = time.time()
    token1 = _make_validated_token(token_hash="sha256:t1", expires_at=now + 3600)
    token2 = _make_validated_token(token_hash="sha256:t2", expires_at=now + 3600)
    token3 = _make_validated_token(token_hash="sha256:t3", expires_at=now + 3600)
    cache.put(token1)
    cache.put(token2)
    cache.put(token3)
    assert cache.get("sha256:t1") is None
    assert cache.get("sha256:t2") is not None
    assert cache.get("sha256:t3") is not None


def test_validator_with_cache_skips_decoding() -> None:
    cache = TokenCache()
    validator = EntraTokenValidator(_config(), signing_key="fake-key", cache=cache)
    token = _make_jwt(_valid_token_payload())
    counter: dict[str, int] = {"count": 0}

    class _CountingJWT:
        @staticmethod
        def decode(t: str, **kw: object) -> dict[str, object]:
            counter["count"] += 1
            return _MockJWT.decode(t, **kw)

    with patch.dict("sys.modules", {"jwt": _CountingJWT()}):
        result1 = validator.validate(token, StepUpLevel.MULTI_FACTOR)
        result2 = validator.validate(token, StepUpLevel.MULTI_FACTOR)

    assert counter["count"] == 1
    assert result1.principal_id == "user-001"
    assert result2.principal_id == "user-001"


# ---------------------------------------------------------------------------
# WI-3.3 — EntraEnvConfig
# ---------------------------------------------------------------------------


def test_entra_env_config_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "ENTRA_TENANT_ID": "tenant-123",
            "ENTRA_CLIENT_ID": "client-456",
            "ENTRA_AUDIENCE": "api://agent-suite",
        },
        clear=False,
    ):
        config = EntraEnvConfig.from_env()
    assert config.tenant_id == "tenant-123"
    assert config.client_id == "client-456"
    assert config.audience == "api://agent-suite"
    assert config.jwks_url == (
        "https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys"
    )
    assert config.is_configured


def test_entra_env_config_is_configured() -> None:
    config = EntraEnvConfig(
        tenant_id="tenant-123",
        client_id="client-456",
        audience="api://agent-suite",
        jwks_url="https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys",
    )
    assert config.is_configured


def test_entra_env_config_not_configured() -> None:
    config = EntraEnvConfig()
    assert not config.is_configured
