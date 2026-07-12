"""Entra (Azure AD) step-up authentication edge adapter.

Validates OAuth2/OIDC tokens from Microsoft Entra ID. This is an edge module:
``PyJWT`` is imported lazily inside methods so the module can be imported
without the ``azure`` extra installed.

Install: ``pip install agent-suite[azure]``

The adapter implements the ``TokenValidator`` protocol from
``agent_suite.dual_control``. JWT signature verification requires a signing
key (JWKS) — if no key is provided, validation fails closed with
``EntraError``. This is a deliberate fail-closed design: the adapter never
accepts a token without verifying its signature.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

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


class EntraTokenValidator:
    """Validates Entra tokens against the dual control ``TokenValidator`` protocol."""

    def __init__(self, config: EntraConfig, *, signing_key: str | bytes | None = None) -> None:
        self._config = config
        self._signing_key = signing_key

    def validate(self, token: str, required_level: StepUpLevel) -> ValidatedToken:
        """Validate an Entra JWT token and return a ``ValidatedToken``.

        Raises ``EntraError`` if any check fails. Fails closed if no signing
        key is configured — tokens are never accepted without signature
        verification.
        """
        if self._signing_key is None:
            raise EntraError(
                "no signing key configured — token validation requires a JWKS key"
            )

        try:
            import jwt  # type: ignore[import-not-found]
        except ImportError:
            raise EntraError(
                "PyJWT not installed — run: pip install agent-suite[azure]"
            )

        try:
            decoded = jwt.decode(
                token,
                key=self._signing_key,
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
        if nbf is not None and isinstance(nbf, (int, float)) and now < nbf:
            raise EntraError("token not yet valid")

        tid = decoded.get("tid", "")
        if tid and tid != self._config.tenant_id:
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

        return ValidatedToken(
            principal_id=principal_id,
            step_up_level=token_level,
            validated_at=now,
            expires_at=float(exp),
            token_hash=_hash_token(token),
        )
