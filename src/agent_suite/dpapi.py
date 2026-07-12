"""Windows DPAPI helper — protects data at rest using the Windows Data Protection API.

This is an edge module: it imports ``win32crypt`` lazily inside functions so the
module can be imported on non-Windows systems without pywin32 installed.
Install the ``windows`` extra (``pip install agent-suite[windows]``) for DPAPI
support.

DPAPI encrypts data using the current user's credentials or the machine key.
The encrypted blob can only be decrypted by the same user (user-scope) or any
user on the same machine (machine-scope). This is the recommended at-rest
protection for signing keys on Windows hosts.
"""

from __future__ import annotations

import sys


class DPAPIError(Exception):
    """Raised when DPAPI operations fail."""


def protect(data: bytes, *, description: str = "agent-suite", machine_scope: bool = False) -> bytes:
    """Encrypt data using DPAPI ``CryptProtectData``.

    Raises ``DPAPIError`` if not on Windows or if pywin32 is not installed.
    Never logs or returns the plaintext.
    """
    if sys.platform != "win32":
        raise DPAPIError("DPAPI requires Windows")
    try:
        import win32crypt  # type: ignore[import-untyped]
    except ImportError:
        raise DPAPIError("pywin32 not installed — run: pip install agent-suite[windows]")

    flags = 0x1 if machine_scope else 0x0  # CRYPTPROTECT_LOCAL_MACHINE = 0x1
    try:
        blob: bytes = win32crypt.CryptProtectData(data, description, None, None, None, flags)
    except Exception as exc:
        raise DPAPIError(f"CryptProtectData failed: {exc}") from exc
    if blob is None:
        raise DPAPIError("CryptProtectData returned None")
    return blob


def unprotect(blob: bytes) -> bytes:
    """Decrypt data using DPAPI ``CryptUnprotectData``.

    Raises ``DPAPIError`` if not on Windows, if pywin32 is not installed,
    or if decryption fails (wrong user/machine, corrupted blob).
    """
    if sys.platform != "win32":
        raise DPAPIError("DPAPI requires Windows")
    try:
        import win32crypt
    except ImportError:
        raise DPAPIError("pywin32 not installed — run: pip install agent-suite[windows]")

    try:
        result: tuple[str, bytes] = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    except Exception as exc:
        raise DPAPIError(f"CryptUnprotectData failed: {exc}") from exc
    plaintext = result[1]
    if plaintext is None:
        raise DPAPIError("CryptUnprotectData returned None")
    return plaintext


def is_available() -> bool:
    """Check if DPAPI is available (Windows + pywin32 installed). Non-secret, non-acting."""
    if sys.platform != "win32":
        return False
    try:
        import win32crypt  # noqa: F401
        return True
    except ImportError:
        return False
