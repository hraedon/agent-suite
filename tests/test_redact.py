from __future__ import annotations

from agent_suite._redact import redact_url


def test_redact_strips_userinfo_keeps_host_and_port() -> None:
    assert redact_url("https://svc:secret@host:8443/path") == "https://host:8443/path"


def test_redact_strips_username_only() -> None:
    assert redact_url("https://svc@host/p") == "https://host/p"


def test_redact_passes_through_url_without_userinfo() -> None:
    assert redact_url("https://host:8443/path") == "https://host:8443/path"


def test_redact_does_not_crash_on_garbage() -> None:
    assert redact_url("not a url at all") == "not a url at all"


def test_redact_empty_username_password_still_redacts() -> None:
    assert redact_url("https://:@host/p") == "https://host/p"
