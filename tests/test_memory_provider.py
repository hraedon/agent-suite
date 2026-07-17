"""Tests for Plan 012 — pluggable memory provider.

Covers WI-0.1 (contract), WI-1.1 (config), WI-1.2 (bootstrap step),
WI-2.1 (doctor section), and WI-3.1 (lock provider extension).

All tests use stubbed runners and installed checks — no live infra.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

import pytest

from agent_suite.bootstrap import (
    StepKind,
    StepStatus,
    run_bootstrap,
)
from agent_suite.config import (
    HINDSIGHT_TENANT_ENV,
    HINDSIGHT_URL_ENV,
    MEMORY_ENGINE_ENV,
    MemoryProviderConfig,
    memory_provider_config,
)
from agent_suite.doctor import (
    SuiteReport,
    aggregate,
    format_text,
)
from agent_suite.lock import (
    DriftKind,
    ProviderExtension,
    SuiteLock,
    check_drift,
    deserialize_lock,
    format_drift_text,
    generate_lock,
    read_provider_extension,
    serialize_lock,
    write_lock_file,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / "data" / "contracts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    """Returns canned output keyed by command prefix (longest match first)."""

    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in sorted(self._outputs.items(), key=lambda x: -len(x[0])):
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                if out.stdout == _INSTALL_OK:
                    return _completed(
                        stdout=(
                            f'{{"tool":"{cmd[0]}","harness":"{cmd[2]}",'
                            '"status":"installed","actions":[],"no_op":false}'
                        )
                    )
                return out
        return _completed(stdout='{"reachable": true, "ok": true}')


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _ok_doctor_json(component: str, version: str = "1.0.0") -> str:
    return json.dumps(
        {
            "component": component,
            "version": version,
            "ok": True,
            "regista": {"reachable": True, "project": "x", "chain_ok": True},
            "checks": [{"name": "regista", "status": "ok", "detail": ""}],
        }
    )


def _mp_doctor_ok(engine: str = "hindsight") -> str:
    return json.dumps(
        {
            "ok": True,
            "engine": engine,
            "state": "indexed",
            "capabilities": ["ingest", "recall", "forget", "synthesize"],
            "version": "1.0.0",
            "protocol_version": "1.0",
            "engine_name": engine,
            "indexing_backlog": 0,
            "indexing_freshness": "2026-07-12T00:00:00Z",
            "detail": "",
        }
    )


def _mp_doctor_fail(engine: str = "hindsight") -> str:
    return json.dumps(
        {
            "ok": False,
            "engine": engine,
            "state": "failed",
            "capabilities": [],
            "version": "1.0.0",
            "protocol_version": "1.0",
            "engine_name": engine,
            "indexing_backlog": 42,
            "indexing_freshness": None,
            "detail": "hindsight unreachable: connection refused",
        }
    )


def _mp_describe_ok(engine: str = "hindsight") -> str:
    return json.dumps(
        {
            "engine": engine,
            "ok": True,
            "capabilities": ["ingest", "recall", "forget", "synthesize"],
            "version": "1.0.0",
            "protocol_version": "1.0",
        }
    )


def _all_ok_outputs() -> dict[tuple[str, ...], subprocess.CompletedProcess[str]]:
    from agent_suite.components import COMPONENTS

    return {
        (c.doctor_cmd[0],): _completed(stdout=_ok_doctor_json(c.ident))
        for c in COMPONENTS
    }


def _aggregate_safe(
    *,
    runner: StubRunner,
    installed=...,
    mp_config: MemoryProviderConfig | None = None,
    memory_provider_checks: bool = True,
) -> SuiteReport:
    if installed is ...:
        installed = _installed_all
    return aggregate(
        installed=installed,
        runner=runner,
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        memory_provider_config=mp_config,
        memory_provider_checks=memory_provider_checks,
    )


# ---------------------------------------------------------------------------
# WI-0.1: Contract file
# ---------------------------------------------------------------------------


def test_contract_file_exists() -> None:
    path = CONTRACTS_DIR / "memory-provider.json"
    assert path.exists(), f"contract fixture missing: {path}"


def test_contract_validates_meta() -> None:
    path = CONTRACTS_DIR / "memory-provider.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for field in ("contract", "version", "description", "owned_by", "consumers", "invariants"):
        assert field in data, f"missing required meta-field '{field}'"
    assert data["contract"] == "memory-provider"
    assert data["version"].count(".") >= 2
    assert isinstance(data["consumers"], list) and len(data["consumers"]) > 0
    assert isinstance(data["invariants"], list) and len(data["invariants"]) > 0


def test_contract_protocol_version() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    assert data["protocol_version"] == "1.0"


def test_contract_capabilities() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    caps = set(data["capabilities"])
    expected = {"ingest", "recall", "forget", "synthesize", "exact_source", "update", "export"}
    assert caps == expected


def test_contract_scope_mappings() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    scopes = set(data["scope_mappings"])
    assert scopes == {"project", "workspace", "user", "agent", "session"}


def test_contract_consistency_states() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    states = set(data["consistency_states"])
    assert states == {"pending", "indexed", "failed", "cancelled", "stale"}


def test_contract_origin_classes() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    origins = set(data["origin_classes"])
    assert origins == {"raw", "extracted", "derived", "synthesized"}


def test_contract_authority_semantics() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    assert "canonical" in data["authority_semantics"].lower()
    assert "untrusted" in data["authority_semantics"].lower()


def test_contract_degradation_semantics() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    assert "unhealthy" in data["degradation_semantics"].lower()
    assert "fallback" in data["degradation_semantics"].lower()


def test_contract_health_shape() -> None:
    data = json.loads((CONTRACTS_DIR / "memory-provider.json").read_text())
    shape = data["health_shape"]
    for key in (
        "state", "capabilities", "version", "protocol_version",
        "engine_name", "indexing_backlog", "indexing_freshness", "detail",
    ):
        assert key in shape, f"health_shape missing key: {key}"


# ---------------------------------------------------------------------------
# WI-1.1: memory_provider_config()
# ---------------------------------------------------------------------------


def test_config_defaults_to_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MEMORY_ENGINE_ENV, raising=False)
    monkeypatch.delenv(HINDSIGHT_URL_ENV, raising=False)
    monkeypatch.delenv(HINDSIGHT_TENANT_ENV, raising=False)
    cfg = memory_provider_config()
    assert cfg["engine"] == "native"
    assert cfg["hindsight_url"] is None
    assert cfg["hindsight_tenant"] == "default"
    assert cfg["endpoint"] is None


def test_config_reads_hindsight_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MEMORY_ENGINE_ENV, "hindsight")
    monkeypatch.setenv(HINDSIGHT_URL_ENV, "https://hindsight-api.example.com")
    monkeypatch.setenv(HINDSIGHT_TENANT_ENV, "acme")
    cfg = memory_provider_config()
    assert cfg["engine"] == "hindsight"
    assert cfg["hindsight_url"] == "https://hindsight-api.example.com"
    assert cfg["hindsight_tenant"] == "acme"
    assert cfg["endpoint"] == "https://hindsight-api.example.com"


def test_config_endpoint_none_for_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MEMORY_ENGINE_ENV, "native")
    monkeypatch.setenv(HINDSIGHT_URL_ENV, "https://hindsight-api.example.com")
    cfg = memory_provider_config()
    assert cfg["endpoint"] is None


def test_memory_provider_config_dataclass_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MEMORY_ENGINE_ENV, "hindsight")
    monkeypatch.setenv(HINDSIGHT_URL_ENV, "https://hindsight-api.example.com")
    monkeypatch.setenv(HINDSIGHT_TENANT_ENV, "acme")
    cfg = MemoryProviderConfig.from_env()
    assert cfg.engine == "hindsight"
    assert cfg.hindsight_url == "https://hindsight-api.example.com"
    assert cfg.hindsight_tenant == "acme"
    assert cfg.endpoint == "https://hindsight-api.example.com"


def test_memory_provider_config_dataclass_defaults() -> None:
    cfg = MemoryProviderConfig()
    assert cfg.engine == "native"
    assert cfg.hindsight_url is None
    assert cfg.hindsight_tenant == "default"
    assert cfg.endpoint is None


# ---------------------------------------------------------------------------
# WI-1.2: Bootstrap MEMORY_PROVIDER step
# ---------------------------------------------------------------------------

_INSTALL_OK = (
    '{"tool":"component","harness":"test","status":"installed",'
    '"actions":[],"no_op":false}'
)


def test_bootstrap_native_engine_done() -> None:
    runner = StubRunner({
        ("regista", "doctor"): _completed(stdout='{"reachable": true, "ok": true}'),
        ("regista", "provision"): _completed(stdout='[{"project": "test", "schema_created": true}]'),
        ("regista", "provision-principal"): _completed(stdout='{"principal_id": "suite-service"}'),
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes", "install-harness"): _completed(stdout=_INSTALL_OK),
        ("cairn",): _completed(stdout=_INSTALL_OK),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
        memory_engine="native",
    )
    assert result.ok is True
    mp_step = next(s for s in result.steps if s.step is StepKind.MEMORY_PROVIDER)
    assert mp_step.status is StepStatus.DONE
    assert "native" in mp_step.detail


def test_bootstrap_hindsight_unreachable_failed() -> None:
    runner = StubRunner({
        ("regista", "doctor"): _completed(stdout='{"reachable": true, "ok": true}'),
        ("regista", "provision"): _completed(stdout='[{"project": "test", "schema_created": true}]'),
        ("regista", "provision-principal"): _completed(stdout='{"principal_id": "suite-service"}'),
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes", "install-harness"): _completed(stdout=_INSTALL_OK),
        ("agent-notes", "memory-provider"): _completed(
            returncode=1, stderr="connection refused"
        ),
        ("cairn",): _completed(stdout=_INSTALL_OK),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
        memory_engine="hindsight",
        hindsight_url="https://hindsight-api.example.com",
    )
    assert result.ok is False
    mp_step = next(s for s in result.steps if s.step is StepKind.MEMORY_PROVIDER)
    assert mp_step.status is StepStatus.FAILED
    assert "unreachable" in mp_step.detail.lower()


def test_bootstrap_hindsight_no_url_failed() -> None:
    runner = StubRunner({
        ("regista", "doctor"): _completed(stdout='{"reachable": true, "ok": true}'),
        ("regista", "provision"): _completed(stdout='[{"project": "test", "schema_created": true}]'),
        ("regista", "provision-principal"): _completed(stdout='{"principal_id": "suite-service"}'),
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes", "install-harness"): _completed(stdout=_INSTALL_OK),
        ("cairn",): _completed(stdout=_INSTALL_OK),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
        memory_engine="hindsight",
        hindsight_url=None,
    )
    assert result.ok is False
    mp_step = next(s for s in result.steps if s.step is StepKind.MEMORY_PROVIDER)
    assert mp_step.status is StepStatus.FAILED
    assert "HINDSIGHT_URL" in mp_step.detail


def test_bootstrap_hindsight_reachable_done() -> None:
    runner = StubRunner({
        ("regista", "doctor"): _completed(stdout='{"reachable": true, "ok": true}'),
        ("regista", "provision"): _completed(stdout='[{"project": "test", "schema_created": true}]'),
        ("regista", "provision-principal"): _completed(stdout='{"principal_id": "suite-service"}'),
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes", "install-harness"): _completed(stdout=_INSTALL_OK),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_describe_ok()),
        ("cairn",): _completed(stdout=_INSTALL_OK),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
        memory_engine="hindsight",
        hindsight_url="https://hindsight-api.example.com",
    )
    assert result.ok is True
    mp_step = next(s for s in result.steps if s.step is StepKind.MEMORY_PROVIDER)
    assert mp_step.status is StepStatus.DONE
    assert "hindsight" in mp_step.detail


def test_bootstrap_memory_provider_dry_run() -> None:
    runner = StubRunner({})
    result = run_bootstrap(
        dry_run=True,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
        memory_engine="hindsight",
        hindsight_url="https://hindsight-api.example.com",
    )
    mp_step = next(s for s in result.steps if s.step is StepKind.MEMORY_PROVIDER)
    assert mp_step.status is StepStatus.PENDING
    assert len(runner.calls) == 0


def test_bootstrap_memory_provider_after_faces() -> None:
    from agent_suite.bootstrap import _INSTALL_ORDER

    faces_idx = _INSTALL_ORDER.index(StepKind.FACES)
    mp_idx = _INSTALL_ORDER.index(StepKind.MEMORY_PROVIDER)
    provenance_idx = _INSTALL_ORDER.index(StepKind.PROVENANCE)
    assert faces_idx < mp_idx < provenance_idx


def test_bootstrap_memory_provider_step_in_tier_01() -> None:
    from agent_suite.bootstrap import BootstrapTier, _steps_for_tier

    steps = _steps_for_tier(BootstrapTier.CORE_01)
    assert StepKind.MEMORY_PROVIDER in steps


# ---------------------------------------------------------------------------
# WI-2.1: Doctor memory_provider section
# ---------------------------------------------------------------------------


def test_doctor_includes_memory_provider_section() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="hindsight", hindsight_url="https://hindsight.example"),
    )
    assert report.memory_provider is not None
    assert report.memory_provider["ok"] is True
    assert report.memory_provider["engine"] == "hindsight"


def test_doctor_memory_provider_in_to_dict() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="hindsight", hindsight_url="https://hindsight.example"),
    )
    d = report.to_dict()
    assert "memory_provider" in d
    assert d["memory_provider"]["engine"] == "hindsight"


def test_doctor_native_memory_provider_does_not_affect_suite_ok() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok("native")),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="native"),
    )
    assert report.suite_ok is True
    assert report.memory_provider is not None


def test_doctor_hindsight_unreachable_makes_suite_not_ok() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_fail()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(
            engine="hindsight",
            hindsight_url="https://hindsight.example",
            endpoint="https://hindsight.example",
        ),
    )
    assert report.suite_ok is False
    assert report.memory_provider is not None
    assert report.memory_provider["ok"] is False


def test_doctor_hindsight_not_configured_does_not_affect_suite_ok() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_fail()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="hindsight", hindsight_url=None, endpoint=None),
    )
    assert report.suite_ok is True


def test_doctor_memory_provider_none_when_checks_disabled() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="hindsight", hindsight_url="https://hindsight.example"),
        memory_provider_checks=False,
    )
    assert report.memory_provider is None


def test_doctor_memory_provider_none_when_not_installed() -> None:
    runner = StubRunner(_all_ok_outputs())
    report = _aggregate_safe(
        runner=runner,
        installed=_installed_none,
        mp_config=MemoryProviderConfig(engine="hindsight", hindsight_url="https://hindsight.example"),
    )
    assert report.memory_provider is None


def test_doctor_memory_provider_text_section() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(
            engine="hindsight",
            hindsight_url="https://hindsight.example",
            endpoint="https://hindsight.example",
        ),
    )
    text = format_text(report)
    assert "memory provider" in text
    assert "hindsight" in text


def test_doctor_memory_provider_not_ok_text() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_fail()),
    })
    report = _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(
            engine="hindsight",
            hindsight_url="https://hindsight.example",
            endpoint="https://hindsight.example",
        ),
    )
    text = format_text(report)
    assert "memory provider" in text
    assert "not ok" in text


def test_doctor_memory_provider_no_extra_call_when_checks_disabled() -> None:
    runner = StubRunner({
        **_all_ok_outputs(),
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_doctor_ok()),
    })
    _aggregate_safe(
        runner=runner,
        mp_config=MemoryProviderConfig(engine="native"),
        memory_provider_checks=False,
    )
    mp_calls = [c for c in runner.calls if "memory-provider" in c]
    assert mp_calls == []


# ---------------------------------------------------------------------------
# WI-3.1: Lock provider extension
# ---------------------------------------------------------------------------


_PROVIDER_EXT = ProviderExtension(
    provider_name="hindsight",
    adapter_version="1.0.0",
    protocol_version="1.0",
    deployment_mode="remote",
    support_level="supported",
    config_digest=None,
)


def test_lock_round_trip_with_provider_extension() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": __import__("agent_suite.lock", fromlist=["ComponentPin"]).ComponentPin(
            repo="YOUR-ORG/regista", version="0.4.0"
        )},
        provider_extension=_PROVIDER_EXT,
    )
    text = serialize_lock(lock)
    restored = deserialize_lock(text)
    assert restored.provider_extension is not None
    assert restored.provider_extension == _PROVIDER_EXT


def test_lock_round_trip_without_provider_extension() -> None:
    from agent_suite.lock import ComponentPin

    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
    )
    text = serialize_lock(lock)
    restored = deserialize_lock(text)
    assert restored.provider_extension is None


def test_lock_serialize_includes_memory_provider_section() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={},
        provider_extension=_PROVIDER_EXT,
    )
    text = serialize_lock(lock)
    assert "[memory_provider]" in text
    assert 'provider_name = "hindsight"' in text
    assert 'protocol_version = "1.0"' in text
    assert 'deployment_mode = "remote"' in text


def test_lock_to_dict_includes_memory_provider() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={},
        provider_extension=_PROVIDER_EXT,
    )
    d = lock.to_dict()
    assert "memory_provider" in d
    assert d["memory_provider"]["provider_name"] == "hindsight"


def test_lock_to_dict_omits_memory_provider_when_none() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={},
    )
    d = lock.to_dict()
    assert "memory_provider" not in d


def test_lock_file_round_trip_with_provider(tmp_path: Path) -> None:
    from agent_suite.lock import ComponentPin

    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
        provider_extension=_PROVIDER_EXT,
    )
    path = tmp_path / "SUITE.lock"
    write_lock_file(lock, path)
    loaded = __import__("agent_suite.lock", fromlist=["load_lock_file"]).load_lock_file(path)
    assert loaded is not None
    assert loaded == lock


def test_lock_drift_detects_provider_mismatch() -> None:
    from agent_suite.lock import ComponentPin

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
        provider_extension=_PROVIDER_EXT,
    )
    current = ProviderExtension(
        provider_name="native",
        adapter_version=None,
        protocol_version="1.0",
        deployment_mode="local",
        support_level="supported",
        config_digest=None,
    )
    result = check_drift(
        locked,
        current_quad=None,
        component_versions={"regista": "0.4.0"},
        current_provider_extension=current,
    )
    assert result.matches is False
    provider_drifts = [d for d in result.drift if d.kind is DriftKind.PROVIDER_DRIFT]
    assert len(provider_drifts) >= 1
    assert any(d.field == "provider_name" for d in provider_drifts)


def test_lock_drift_provider_missing_when_locked() -> None:
    from agent_suite.lock import ComponentPin

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
        provider_extension=_PROVIDER_EXT,
    )
    result = check_drift(
        locked,
        current_quad=None,
        component_versions={"regista": "0.4.0"},
        current_provider_extension=None,
    )
    assert result.matches is False
    provider_drifts = [d for d in result.drift if d.kind is DriftKind.PROVIDER_DRIFT]
    assert len(provider_drifts) == 1
    assert provider_drifts[0].locked == "pinned"
    assert provider_drifts[0].current == "absent"


def test_lock_drift_provider_unexpected_when_not_locked() -> None:
    from agent_suite.lock import ComponentPin

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
        provider_extension=None,
    )
    result = check_drift(
        locked,
        current_quad=None,
        component_versions={"regista": "0.4.0"},
        current_provider_extension=_PROVIDER_EXT,
    )
    assert result.matches is False
    provider_drifts = [d for d in result.drift if d.kind is DriftKind.PROVIDER_DRIFT]
    assert len(provider_drifts) == 1
    assert provider_drifts[0].locked == "(not pinned)"
    assert provider_drifts[0].current == "present"


def test_lock_drift_no_drift_when_provider_matches() -> None:
    from agent_suite.lock import ComponentPin

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
        provider_extension=_PROVIDER_EXT,
    )
    result = check_drift(
        locked,
        current_quad=None,
        component_versions={"regista": "0.4.0"},
        current_provider_extension=_PROVIDER_EXT,
    )
    assert result.matches is True
    assert result.drift == []


def test_lock_format_drift_text_provider() -> None:
    from agent_suite.lock import DriftEntry, LockDriftResult

    result = LockDriftResult(
        matches=False,
        note="1 drift(s)",
        drift=[
            DriftEntry(
                kind=DriftKind.PROVIDER_DRIFT,
                component="memory_provider",
                field="provider_name",
                locked="hindsight",
                current="native",
            ),
        ],
    )
    text = format_drift_text(result)
    assert "memory_provider" in text
    assert "provider_name" in text
    assert "hindsight" in text
    assert "native" in text


@pytest.mark.parametrize("kind", list(DriftKind))
def test_drift_kind_format_is_total(kind: DriftKind) -> None:
    from agent_suite.lock import DriftEntry, LockDriftResult

    entry = DriftEntry(
        kind=kind, component="x", field="version", locked="1", current="2"
    )
    result = LockDriftResult(matches=False, note="test", drift=[entry])
    text = format_drift_text(result)
    assert isinstance(text, str)


# ---------------------------------------------------------------------------
# read_provider_extension
# ---------------------------------------------------------------------------


def test_read_provider_extension_native_returns_none() -> None:
    result = read_provider_extension(
        engine="native",
        runner=StubRunner({}),
        installed=_installed_all,
    )
    assert result is None


def test_read_provider_extension_hindsight_parses() -> None:
    runner = StubRunner({
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_describe_ok()),
    })
    result = read_provider_extension(
        engine="hindsight",
        runner=runner,
        installed=_installed_all,
    )
    assert result is not None
    assert result.provider_name == "hindsight"
    assert result.adapter_version == "1.0.0"
    assert result.protocol_version == "1.0"
    assert result.deployment_mode == "remote"
    assert result.support_level == "supported"


def test_read_provider_extension_not_installed() -> None:
    result = read_provider_extension(
        engine="hindsight",
        runner=StubRunner({}),
        installed=_installed_none,
    )
    assert result is None


def test_read_provider_extension_nonzero_exit() -> None:
    runner = StubRunner({
        ("agent-notes", "memory-provider"): _completed(returncode=1, stderr="error"),
    })
    result = read_provider_extension(
        engine="hindsight",
        runner=runner,
        installed=_installed_all,
    )
    assert result is None


def test_read_provider_extension_bad_json() -> None:
    runner = StubRunner({
        ("agent-notes", "memory-provider"): _completed(stdout="not json"),
    })
    result = read_provider_extension(
        engine="hindsight",
        runner=runner,
        installed=_installed_all,
    )
    assert result is None


# ---------------------------------------------------------------------------
# generate_lock with memory_engine
# ---------------------------------------------------------------------------


def test_generate_lock_native_no_provider_extension() -> None:
    from agent_suite.components import COMPONENTS

    lock = generate_lock(
        component_versions={c.ident: "1.0.0" for c in COMPONENTS},
        runner=StubRunner({}),
        installed=_installed_all,
        memory_engine="native",
    )
    assert lock.provider_extension is None


def test_generate_lock_hindsight_adds_provider_extension() -> None:
    from agent_suite.components import COMPONENTS

    runner = StubRunner({
        ("agent-notes", "memory-provider"): _completed(stdout=_mp_describe_ok()),
    })
    lock = generate_lock(
        component_versions={c.ident: "1.0.0" for c in COMPONENTS},
        runner=runner,
        installed=_installed_all,
        memory_engine="hindsight",
    )
    assert lock.provider_extension is not None
    assert lock.provider_extension.provider_name == "hindsight"
    assert lock.provider_extension.adapter_version == "1.0.0"
