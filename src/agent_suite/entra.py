"""Entra (Azure AD) step-up authentication edge adapter.

Validates OAuth2/OIDC tokens from Microsoft Entra ID. This is an edge module:
``PyJWT`` is imported lazily inside methods so the module can be imported
without the ``azure`` extra installed.

Install: ``pip install agent-suite[azure]``

The adapter implements the ``TokenValidator`` protocol from
``agent_suite.dual_control``. JWT signature verification requires a signing
key — either provided directly or fetched automatically from the Entra JWKS
endpoint. If neither is configured, validation fails closed with
``EntraError``. This is a deliberate fail-closed design: the adapter never
accepts a token without verifying its signature.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from agent_suite.dual_control import StepUpLevel, ValidatedToken, _hash_token, _step_up_rank


class EntraError(Exception):
    """Raised when Entra token validation fails."""


_ACR_TO_LEVEL: dict[str, StepUpLevel] = {
    "urn:microsoft:entra:1f:singlefactor": StepUpLevel.SINGLE_FACTOR,
    "urn:microsoft:entra:2f:mfa": StepUpLevel.MULTI_FACTOR,
    "urn:microsoft:entra:3f:hardtoken": StepUpLevel.HARD_TOKEN,
}

_LEVEL_TO_ACR: dict[StepUpLevel, str] = {
    v: k for k, v in _ACR_TO_LEVEL.items()
}


@dataclass(frozen=True)
class EntraConfig:
    tenant_id: str
    client_id: str
    issuer: str
    audience: str


def default_jwks_url(config: EntraConfig) -> str:
    """Construct the standard Microsoft Entra JWKS discovery URL."""
    return f"https://login.microsoftonline.com/{config.tenant_id}/discovery/v2.0/keys"


class TokenCache:
    """Caches validated tokens by token_hash to avoid re-decoding."""

    def __init__(self, *, max_entries: int = 256) -> None:
        self._entries: OrderedDict[str, ValidatedToken] = OrderedDict()
        self._max_entries = max_entries

    def get(self, token_hash: str) -> ValidatedToken | None:
        """Return cached token if still valid, None otherwise."""
        entry = self._entries.get(token_hash)
        if entry is None:
            return None
        if entry.is_expired():
            del self._entries[token_hash]
            return None
        self._entries.move_to_end(token_hash)
        return entry

    def put(self, token: ValidatedToken) -> None:
        """Cache a validated token. Evicts expired entries."""
        self.cleanup()
        self._entries[token.token_hash] = token
        self._entries.move_to_end(token.token_hash)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def cleanup(self) -> int:
        """Remove expired entries. Returns count removed."""
        expired_hashes = [
            h for h, t in self._entries.items() if t.is_expired()
        ]
        for h in expired_hashes:
            del self._entries[h]
        return len(expired_hashes)


class EntraTokenValidator:
    """Validates Entra tokens against the dual control ``TokenValidator`` protocol."""

    def __init__(
        self,
        config: EntraConfig,
        *,
        signing_key: str | bytes | None = None,
        jwks_url: str | None = None,
        cache: TokenCache | None = None,
        _jwks_cache_ttl: float = 300.0,
    ) -> None:
        self._config = config
        self._signing_key = signing_key
        self._jwks_url = jwks_url
        self._cache = cache
        self._jwks_cache_ttl = _jwks_cache_ttl
        self._jwks_client: Any = None
        self._last_jwks_fetch: float = 0.0

    def _get_jwks_key(self, token: str) -> Any:
        try:
            import jwt
        except ImportError:
            raise EntraError(
                "PyJWT not installed — run: pip install agent-suite[azure]"
            )

        assert self._jwks_url is not None

        now = time.time()
        if (
            self._jwks_client is None
            or now - self._last_jwks_fetch > self._jwks_cache_ttl
        ):
            self._jwks_client = jwt.PyJWKClient(self._jwks_url)
            self._last_jwks_fetch = now

        try:
            signing_jwk = self._jwks_client.get_signing_key_from_jwt(token)
            return signing_jwk.key
        except Exception as exc:
            raise EntraError(f"JWKS key fetch failed: {exc}") from exc

    def validate(self, token: str, required_level: StepUpLevel) -> ValidatedToken:
        """Validate an Entra JWT token and return a ``ValidatedToken``.

        Raises ``EntraError`` if any check fails. Fails closed if no signing
        key is configured — tokens are never accepted without signature
        verification.
        """
        token_hash = _hash_token(token)

        if self._cache is not None:
            cached = self._cache.get(token_hash)
            if cached is not None:
                if _step_up_rank(cached.step_up_level) >= _step_up_rank(required_level):
                    return cached

        if self._signing_key is None and self._jwks_url is None:
            raise EntraError(
                "no signing key configured — token validation requires a JWKS key"
            )

        try:
            import jwt
        except ImportError:
            raise EntraError(
                "PyJWT not installed — run: pip install agent-suite[azure]"
            )

        if self._signing_key is not None:
            decode_key: Any = self._signing_key
        else:
            decode_key = self._get_jwks_key(token)

        try:
            decoded = jwt.decode(
                token,
                key=decode_key,
                algorithms=["RS256"],
                audience=self._config.audience,
                issuer=self._config.issuer,
            )
        except Exception as exc:
            raise EntraError(f"token decode/signature verification failed: {exc}") from exc

        principal_id = decoded.get("oid") or decoded.get("sub", "")
        if not principal_id or not isinstance(principal_id, str):
            raise EntraError("token missing or invalid principal identifier (oid/sub)")

        exp = decoded.get("exp")
        if not isinstance(exp, (int, float)) or exp <= 0:
            raise EntraError("token has invalid or missing exp claim")

        now = time.time()
        if now >= exp:
            raise EntraError("token expired")

        nbf = decoded.get("nbf")
        if nbf is not None:
            if not isinstance(nbf, (int, float)):
                raise EntraError("token has invalid nbf claim")
            if now < nbf:
                raise EntraError("token not yet valid")

        tid = decoded.get("tid")
        if not tid or not isinstance(tid, str):
            raise EntraError("token missing or invalid tid claim")
        if tid != self._config.tenant_id:
            raise EntraError("token tenant_id does not match configuration")

        acr = decoded.get("acr", "")
        if not isinstance(acr, str):
            raise EntraError("token has invalid acr claim")

        token_level = _ACR_TO_LEVEL.get(acr)
        if token_level is None:
            raise EntraError(f"unrecognized acr value: {acr}")

        if _step_up_rank(token_level) < _step_up_rank(required_level):
            raise EntraError(
                f"step-up requirement not met: "
                f"required {required_level.value} (acr={_LEVEL_TO_ACR.get(required_level, '?')}), "
                f"got {token_level.value} (acr={acr})"
            )

        result = ValidatedToken(
            principal_id=principal_id,
            step_up_level=token_level,
            validated_at=now,
            expires_at=float(exp),
            token_hash=token_hash,
        )

        if self._cache is not None:
            self._cache.put(result)

        return result
