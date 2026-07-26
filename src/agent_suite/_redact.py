from __future__ import annotations

import urllib.parse


def redact_url(url: str) -> str:
    """Strip embedded userinfo so an operator endpoint URL can be logged safely.

    Operator-configured endpoints (DOSSIER_URL, HINDSIGHT_URL, ...) may carry
    service credentials in the userinfo component (https://svc:secret@host/).
    Detail strings, doctor output, and bootstrap logs must reference the host,
    never the value. A URL with no userinfo is returned unchanged; an unparseable
    value is returned unchanged rather than crashing the caller.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except (ValueError, TypeError):
        return url
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or ""
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))
