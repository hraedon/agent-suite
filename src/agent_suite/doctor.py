"""The doctor umbrella — aggregate each component's health into one report.

Implements Plan 001 WI-1.1. `agent-suite doctor` shells each installed component's
`<tool> doctor --json` (the common shape regista Plan 025 WI-3.1 defines) and folds
them into the umbrella shape from `docs/bootstrap-contract.md` §3.

Honest-health rules (AGENTS.md): a component that isn't installed is `absent` (a
named state, not silence — and not a failure for an optional tier); a component
that's installed but unreachable or reports `ok:false` is a failure. The umbrella
is strictly read-only.

The component `<tool> doctor --json` contract requires a top-level `ok` boolean.
Components that omit it are treated as failed (fail-honest: unknown health is
not healthy). A missing/non-JSON result is a named status, never a traceback.
"""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite import key_watch
from agent_suite import lock
from agent_suite import runtime_provenance
from agent_suite import verify_restore
from agent_suite.codex_catalog import CODEX_PLUGIN_CATALOG, CodexPluginId, with_marketplace
from agent_suite.codex_health import CodexHealthReport, check_codex_health, format_codex_health_text
from agent_suite.components import COMPONENTS, Component, Locality, Tier
from agent_suite.config import MemoryProviderConfig
from agent_suite.profiles import (
    Profile,
    ProfileClassification,
    classify_doctor,
    profile_label,
)

DEFAULT_GLOBAL_DEADLINE: float = 60.0


class ComponentStatus(Enum):
    """The closed set of per-component health states.

    `assert_never` is used over this enum so a newly added status can't be silently
    unhandled in the aggregation or gating logic.
    """

    OK = "ok"  # installed; doctor green
    DEGRADED = "degraded"  # installed; ok but in a non-fatal degrade mode (e.g. coordinator-absent)
    REMOTE = "remote"  # shared service not installed locally; endpoint reachable and healthy (Plan 004 WI-1.6)
    ABSENT = "absent"  # not installed on this box
    NOT_CONFIGURED = (
        "not_configured"  # shared service with no endpoint configured (Plan 004 WI-1.6)
    )
    UNREACHABLE = "unreachable"  # installed, but the doctor command could not be run/caught
    FAILED = "failed"  # installed; doctor exited non-zero, emitted no JSON, or reported ok:false


class Runner(Protocol):
    """Run a component's doctor command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches `shutil.which`)."""

    def __call__(self, cli_name: str) -> bool: ...


class RevisionProbe(Protocol):
    """Probe source revisions attributable to deployed component artifacts.

    Returns a map of component ident → full git SHA (or ``None`` when the
    installed artifact has no trustworthy PEP 610 revision). Defaults to
    :func:`agent_suite.runtime_provenance.read_runtime_revisions`; unrelated
    candidate workspaces never participate in deployed-health decisions.
    """

    def __call__(self) -> dict[str, str | None]: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


@dataclass
class RemoteHealthResult:
    """Result of checking a shared-service component's health endpoint."""

    ok: bool
    version: str | None = None
    detail: str = ""


class RemoteHealthChecker(Protocol):
    """Check a shared-service component's health endpoint (Plan 004 WI-1.6).

    Given the base URL, return a ``RemoteHealthResult``. The default
    implementation does ``GET <url>/healthz`` and parses the JSON response
    for ``ok`` and ``version`` fields — the same shape as the local
    ``<tool> doctor --json`` contract.
    """

    def __call__(self, url: str) -> RemoteHealthResult: ...


def _default_remote_check(url: str) -> RemoteHealthResult:
    """Default remote health check: GET <url>/healthz, parse JSON.

    Uses only stdlib (urllib) — no external HTTP library. A non-200 status,
    connection error, timeout, or invalid JSON is a named failure, never a
    traceback (the doctor is read-only and must never crash).

    Security: redirects are NOT followed (prevents SSRF via an attacker-
    controlled ``DOSSIER_URL`` redirecting to internal services). The URL
    scheme must be ``http`` or ``https`` — ``file:``, ``ftp:``, etc. are
    rejected before any request is made.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return RemoteHealthResult(
            ok=False,
            detail=f"refusing non-http(s) URL scheme '{parsed.scheme}' for {url}",
        )
    healthz_url = f"{url.rstrip('/')}/healthz"

    class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: object, **kwargs: object) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(healthz_url, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return RemoteHealthResult(
                ok=False, detail=f"redirect refused from {healthz_url} (SSRF guard)"
            )
        return RemoteHealthResult(ok=False, detail=f"HTTP {exc.code} from {healthz_url}")
    except urllib.error.URLError as exc:
        return RemoteHealthResult(ok=False, detail=f"unreachable: {healthz_url} ({exc.reason})")
    except Exception as exc:
        return RemoteHealthResult(ok=False, detail=f"error checking {healthz_url}: {exc}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return RemoteHealthResult(ok=False, detail=f"non-JSON response from {healthz_url}")

    if not isinstance(data, dict):
        return RemoteHealthResult(
            ok=False, detail=f"healthz returned non-dict JSON ({type(data).__name__})"
        )

    return RemoteHealthResult(
        ok=bool(data.get("ok", False)),
        version=data.get("version"),
        detail=data.get("detail", ""),
    )


@dataclass
class ComponentReport:
    component: str
    tier: Tier
    status: ComponentStatus
    ok: bool = False
    version: str | None = None
    detail: str = ""
    regista: dict[str, object] | None = None
    checks: list[dict[str, object]] = field(default_factory=list)
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "tier": self.tier.value,
            "status": self.status.value,
            "ok": self.ok,
            "version": self.version,
            "detail": self.detail,
            "regista": self.regista,
            "checks": self.checks,
            "duration_ms": self.duration_ms,
        }


def _check_lock_drift(
    reports: list[ComponentReport],
    *,
    lock_path: Path = lock.DEFAULT_LOCK_PATH,
    version_runner: lock.VersionRunner = lock._default_runner,
    version_installed: lock.Installed = lock._default_installed,
    revision_probe: RevisionProbe = runtime_provenance.read_runtime_revisions,
    current_provider_extension: lock.ProviderExtension | None = None,
) -> lock.LockDriftResult:
    """Compare installed component versions against SUITE.lock.

    Uses the regista quad from ``regista version --json`` (not the doctor
    output, which lacks the full quad) so the schema/workflow/envelope versions
    are checked too — not just the library version. Probes each component's
    installed artifact for an attributable SHA via ``revision_probe``
    (defaulting to
    :func:`agent_suite.runtime_provenance.read_runtime_revisions`) so revision
    drift is based on executed code rather than a nearby development checkout.

    A malformed lock file is a named state (``matches=False``), not a crash —
    the doctor is read-only and must never traceback.
    """
    try:
        existing = lock.load_lock_file(lock_path)
    except ValueError as exc:
        return lock.LockDriftResult(
            matches=False,
            note=f"SUITE.lock is unreadable: {exc}",
        )
    component_versions: dict[str, str | None] = {r.component: r.version for r in reports}
    current_quad = lock.read_regista_quad(runner=version_runner, installed=version_installed)
    # Probe revisions only when there's a lock to compare against — no point
    # shelling out to git when no lock exists (``check_drift`` short-circuits
    # to ``matches=None`` anyway). This also keeps ``aggregate()`` hermetic
    # for callers that have no lock file (the common test fixture).
    try:
        component_revisions: dict[str, str | None] = (
            revision_probe() if existing is not None else {}
        )
    except Exception as exc:  # the doctor must fail closed, never traceback
        return lock.LockDriftResult(
            matches=False,
            note=f"runtime revision provenance probe failed: {type(exc).__name__}",
        )
    return lock.check_drift(
        existing,
        current_quad=current_quad,
        component_versions=component_versions,
        component_revisions=component_revisions,
        current_provider_extension=current_provider_extension,
    )


@dataclass
class SuiteReport:
    suite_ok: bool
    components: list[ComponentReport]
    lock: lock.LockDriftResult = field(
        default_factory=lambda: lock.LockDriftResult(matches=None, note="")
    )
    post_restore: verify_restore.VerifyRestoreResult | None = None
    key_rotation: key_watch.KeyRotationResult | None = None
    store_growth: key_watch.StoreGrowthResult | None = None
    profile_classification: ProfileClassification | None = None
    memory_provider: dict[str, object] | None = None
    codex_health: CodexHealthReport | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "suite_ok": self.suite_ok,
            "components": [c.to_dict() for c in self.components],
            "lock": self.lock.to_dict(),
            "duration_ms": self.duration_ms,
        }
        if self.post_restore is not None:
            d["post_restore"] = self.post_restore.to_dict()
        if self.key_rotation is not None:
            d["key_rotation"] = self.key_rotation.to_dict()
        if self.store_growth is not None:
            d["store_growth"] = self.store_growth.to_dict()
        if self.profile_classification is not None:
            d["profile_classification"] = self.profile_classification.to_dict()
        if self.memory_provider is not None:
            d["memory_provider"] = self.memory_provider
        if self.codex_health is not None:
            d["codex_health"] = self.codex_health.to_dict()
        return d


def _check_shared_service(
    comp: Component,
    *,
    endpoints: dict[str, str],
    remote_checker: RemoteHealthChecker,
) -> ComponentReport:
    """Check a shared-service component by endpoint (Plan 004 WI-1.6).

    When no endpoint is configured, the component is ``NOT_CONFIGURED`` — a
    named state distinct from both ``ABSENT`` (not installed) and ``FAILED``
    (broken). When an endpoint is configured, the doctor probes ``<url>/healthz``
    and renders ``remote: ok @ <version>`` on success or a legible failure
    naming the URL on failure.
    """
    endpoint = endpoints.get(comp.ident)
    if not endpoint:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.NOT_CONFIGURED,
            ok=False,
            detail=f"{comp.ident} not configured (shared service)",
        )

    result = remote_checker(endpoint)
    if result.ok:
        ver = result.version or "unknown"
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.REMOTE,
            ok=True,
            version=result.version,
            detail=f"remote: ok @ {ver}",
        )
    return ComponentReport(
        component=comp.ident,
        tier=comp.tier,
        status=ComponentStatus.FAILED,
        ok=False,
        detail=f"remote endpoint {endpoint}: {result.detail}",
    )


def _check_one(
    comp: Component,
    *,
    installed: Installed,
    runner: Runner,
    remote_checker: RemoteHealthChecker = _default_remote_check,
    shared_endpoints: dict[str, str] | None = None,
) -> ComponentReport:
    cli_name = comp.doctor_cmd[0]

    if not installed(cli_name):
        # Not installed locally — for shared-service components, check the
        # configured endpoint instead of reporting absent (Plan 004 WI-1.6).
        match comp.locality:
            case Locality.SHARED_SERVICE:
                return _check_shared_service(
                    comp,
                    endpoints=shared_endpoints or {},
                    remote_checker=remote_checker,
                )
            case Locality.PER_BOX:
                return ComponentReport(
                    component=comp.ident,
                    tier=comp.tier,
                    status=ComponentStatus.ABSENT,
                    ok=False,
                    detail=f"{cli_name} not installed (tier: {comp.tier.value})",
                )
            case other:
                assert_never(other)

    try:
        result = runner(comp.doctor_cmd)
    except FileNotFoundError:
        # Race: was installed at the check, gone at the run. Treat as absent.
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.ABSENT,
            ok=False,
            detail=f"{cli_name} not found at run time",
        )
    except subprocess.TimeoutExpired:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.UNREACHABLE,
            ok=False,
            detail=f"{cli_name} doctor timed out",
        )
    except OSError as exc:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.UNREACHABLE,
            ok=False,
            detail=f"{cli_name} doctor could not run: {exc}",
        )

    # Try to parse JSON regardless of exit code — a component may exit 1
    # (because ok:false) while still emitting valid JSON with check details.
    # Plan 004 WI-1.4: capture the component's own detail, never "no stderr".
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        if result.returncode != 0:
            return ComponentReport(
                component=comp.ident,
                tier=comp.tier,
                status=ComponentStatus.FAILED,
                ok=False,
                detail=f"{cli_name} doctor exit {result.returncode}: "
                f"{result.stderr.strip() or 'no stderr'}",
            )
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor emitted non-JSON stdout",
        )

    if not isinstance(data, dict):
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor emitted JSON but not a dict (got {type(data).__name__})",
        )

    if "ok" not in data:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor did not emit top-level 'ok' field",
        )

    ok = bool(data.get("ok", False))
    degraded = bool(data.get("degraded", False))

    if not ok:
        status = ComponentStatus.FAILED
    elif degraded:
        status = ComponentStatus.DEGRADED
    else:
        status = ComponentStatus.OK

    regista = data.get("regista")
    checks = data.get("checks", [])
    return ComponentReport(
        component=comp.ident,
        tier=comp.tier,
        status=status,
        ok=ok,
        version=data.get("version"),
        detail=data.get("detail", ""),
        regista=regista if isinstance(regista, dict) else None,
        checks=checks if isinstance(checks, list) else [],
    )


def _compute_suite_ok(reports: list[ComponentReport]) -> bool:
    # Any installed-but-broken component fails the suite (contract: installed but
    # unreachable is a failure). The `assert_never` in the default arm keeps the
    # status enum closed — a newly added status can't slip through ungated.
    for r in reports:
        match r.status:
            case ComponentStatus.UNREACHABLE | ComponentStatus.FAILED:
                return False
            case (
                ComponentStatus.OK
                | ComponentStatus.DEGRADED
                | ComponentStatus.ABSENT
                | ComponentStatus.REMOTE
                | ComponentStatus.NOT_CONFIGURED
            ):
                continue
            case other:
                assert_never(other)

    # Spine absent => no functioning suite.
    if any(r.tier is Tier.SPINE and r.status is ComponentStatus.ABSENT for r in reports):
        return False

    # Nothing deployed at all => not ok (don't smooth an empty box into "healthy").
    # A suite where every component is absent or not-configured has no functioning
    # piece — REMOTE counts as functioning (a shared service is reachable).
    if all(r.status in (ComponentStatus.ABSENT, ComponentStatus.NOT_CONFIGURED) for r in reports):
        return False

    return True


_MEMORY_PROVIDER_DOCTOR_CMD: tuple[str, ...] = (
    "agent-notes",
    "memory-provider",
    "doctor",
    "--json",
)


def _check_memory_provider(
    *,
    installed: Installed,
    runner: Runner,
    mp_config: MemoryProviderConfig,
) -> dict[str, object] | None:
    """Shell ``agent-notes memory-provider doctor --json`` and parse the result.

    Returns ``None`` when agent-notes is not installed. Returns a dict with
    at least ``engine`` and ``ok`` keys on success or failure. Never raises
    — the doctor is read-only and must never traceback.
    """
    if not installed("agent-notes"):
        return None
    try:
        result = runner(_MEMORY_PROVIDER_DOCTOR_CMD)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "engine": mp_config.engine,
            "detail": "agent-notes memory-provider doctor timed out",
        }
    except OSError as exc:
        return {
            "ok": False,
            "engine": mp_config.engine,
            "detail": f"agent-notes memory-provider doctor could not run: {exc}",
        }

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "engine": mp_config.engine,
            "detail": "agent-notes memory-provider doctor emitted non-JSON stdout",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "engine": mp_config.engine,
            "detail": "agent-notes memory-provider doctor emitted non-dict JSON",
        }

    return data


def _check_one_timed(
    comp: Component,
    *,
    installed: Installed,
    runner: Runner,
    remote_checker: RemoteHealthChecker,
    shared_endpoints: dict[str, str] | None,
) -> ComponentReport:
    start = time.monotonic()
    report = _check_one(
        comp,
        installed=installed,
        runner=runner,
        remote_checker=remote_checker,
        shared_endpoints=shared_endpoints,
    )
    report.duration_ms = round((time.monotonic() - start) * 1000, 1)
    return report


def aggregate(
    *,
    installed: Installed = _default_installed,
    runner: Runner = _default_runner,
    components: tuple[Component, ...] = COMPONENTS,
    lock_path: Path | None = None,
    version_runner: lock.VersionRunner | None = None,
    version_installed: lock.Installed | None = None,
    revision_probe: RevisionProbe | None = None,
    verify_restore_dsn: str | None = None,
    key_watch_checks: bool = True,
    profile: Profile | None = None,
    shared_endpoints: dict[str, str] | None = None,
    remote_checker: RemoteHealthChecker | None = None,
    memory_provider_config: MemoryProviderConfig | None = None,
    memory_provider_checks: bool = True,
    codex_health_checks: bool = True,
    codex_marketplace: str | None = None,
    lock_checks: bool = True,
    probe_deadline: float = DEFAULT_GLOBAL_DEADLINE,
) -> SuiteReport:
    """Run each component's doctor and fold into one umbrella report.

    Both `installed` and `runner` are injectable so tests drive aggregation against
    stubbed component doctors with no real binaries on PATH (no live infra in CI).
    `lock_path`, `version_runner`, and `version_installed` control the lock-drift
    check (also injectable for the same reason). `revision_probe` (defaulting to
    :func:`agent_suite.runtime_provenance.read_runtime_revisions`) supplies only
    revisions attributable to installed artifacts; inject a no-op
    (``lambda: {}``) for hermetic tests. A drifted lock
    (``lock.matches is False``) makes ``suite_ok`` False —
    the umbrella must not report a green suite over a red lock.

    Component probes run concurrently (``concurrent.futures``) with a
    ``probe_deadline`` (default 60 s, capped to 30 s) that bounds how long the
    collector waits for results. Each report carries ``duration_ms`` so slow
    probes are visible in the JSON output. The per-probe subprocess timeout
    remains 30 s (set by ``_default_runner``); ``probe_deadline`` bounds the
    *collection* window so the umbrella never hangs indefinitely even if an
    injected runner misbehaves.

    When ``verify_restore_dsn`` is provided, the post-restore chain verification
    (``verify_restore``) runs across every project and the result is attached to
    the report as ``post_restore``. This is the WI-4.2 wiring: a post-restore
    ``doctor --verify-restore`` proves the restored store is cryptographically
    intact, not just reachable. Read-only — ``regista replay`` never mutates.

    When ``key_watch_checks`` is True (default), the key-rotation-age and
    store-growth checks (Plan 005 WI-2.2) run and attach to the report. A key
    past its rotation cadence makes ``suite_ok`` False; store growth is
    informational. These checks are read-only and use the same ``runner`` /
    ``installed`` as the component checks.

    When ``profile`` is set (Plan 008 WI-0.1), the doctor classifies the
    installation against the profile matrix and attaches the result as
    ``profile_classification``. The classification reports the detected profile,
    any missing required components, and any extra optional components.

    When ``shared_endpoints`` is provided (Plan 004 WI-1.6), shared-service
    components that are not installed locally are checked by endpoint instead of
    being reported as absent. ``remote_checker`` is injectable for testing.

    When ``memory_provider_checks`` is True (default) and agent-notes is
    installed, the doctor shells ``agent-notes memory-provider doctor --json``
    and attaches the result as ``memory_provider`` (Plan 012 WI-2.1). A native
    engine never affects ``suite_ok``; a configured Hindsight outage (endpoint
    set but doctor reports not-ok) makes ``suite_ok`` False. Hindsight without
    an endpoint is treated the same as native. ``memory_provider_config`` is
    injectable for testing.

    ``codex_marketplace`` overrides the release marketplace identity used for
    Codex plugin health. This preserves qualified ``name@marketplace`` pinning
    while allowing a local dogfood marketplace to be checked honestly.
    """
    t0 = time.monotonic()
    rc: RemoteHealthChecker = (
        remote_checker if remote_checker is not None else _default_remote_check
    )

    collection_timeout = min(30.0, probe_deadline)
    reports: list[ComponentReport] = []
    collected_idents: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(components), 8)
    ) as pool:
        futures = {
            pool.submit(
                _check_one_timed,
                c,
                installed=installed,
                runner=runner,
                remote_checker=rc,
                shared_endpoints=shared_endpoints,
            ): c
            for c in components
        }
        try:
            for future in concurrent.futures.as_completed(
                futures, timeout=collection_timeout
            ):
                comp = futures[future]
                try:
                    report = future.result(timeout=0)
                    reports.append(report)
                    collected_idents.add(comp.ident)
                except Exception as exc:
                    reports.append(
                        ComponentReport(
                            component=comp.ident,
                            tier=comp.tier,
                            status=ComponentStatus.UNREACHABLE,
                            ok=False,
                            detail=f"{comp.doctor_cmd[0]} doctor raised: {exc}",
                        )
                    )
                    collected_idents.add(comp.ident)
        except TimeoutError:
            pass
        for future, comp in futures.items():
            if comp.ident not in collected_idents:
                reports.append(
                    ComponentReport(
                        component=comp.ident,
                        tier=comp.tier,
                        status=ComponentStatus.UNREACHABLE,
                        ok=False,
                        detail=f"{comp.doctor_cmd[0]} doctor exceeded probe deadline",
                    )
                )
        pool.shutdown(wait=False, cancel_futures=True)

    reports.sort(key=lambda r: next(
        (i for i, c in enumerate(components) if c.ident == r.component), 0
    ))

    mp_config = (
        memory_provider_config
        if memory_provider_config is not None
        else MemoryProviderConfig.from_env()
    )
    memory_provider: dict[str, object] | None = None
    if memory_provider_checks:
        memory_provider = _check_memory_provider(
            installed=installed,
            runner=runner,
            mp_config=mp_config,
        )

    current_provider_extension: lock.ProviderExtension | None = None
    lock_result = lock.LockDriftResult(matches=None, note="")
    if lock_checks:
        current_provider_extension = lock.read_provider_extension(
            engine=mp_config.engine,
            runner=version_runner if version_runner is not None else lock._default_runner,
            installed=version_installed if version_installed is not None else lock._default_installed,
        )

        rprobe: RevisionProbe = (
            revision_probe
            if revision_probe is not None
            else runtime_provenance.read_runtime_revisions
        )
        lock_result = _check_lock_drift(
            reports,
            lock_path=lock_path if lock_path is not None else lock.DEFAULT_LOCK_PATH,
            version_runner=version_runner if version_runner is not None else lock._default_runner,
            version_installed=version_installed
            if version_installed is not None
            else lock._default_installed,
            revision_probe=rprobe,
            current_provider_extension=current_provider_extension,
        )
    post_restore: verify_restore.VerifyRestoreResult | None = None
    if verify_restore_dsn is not None:
        post_restore = verify_restore.verify_restore(
            dsn=verify_restore_dsn,
            installed=installed,
        )
    key_rotation: key_watch.KeyRotationResult | None = None
    store_growth: key_watch.StoreGrowthResult | None = None
    if key_watch_checks:
        key_rotation = key_watch.check_key_rotation(runner=runner, installed=installed)
        store_growth = key_watch.check_store_growth(runner=runner, installed=installed)

    profile_classification: ProfileClassification | None = None
    if profile is not None:
        component_statuses = {r.component: r.status.value for r in reports}
        profile_classification = classify_doctor(component_statuses, reference_profile=profile)

    suite_ok = _compute_suite_ok(reports)
    if post_restore is not None and not post_restore.ok:
        suite_ok = False
    if key_rotation is not None and not key_rotation.ok:
        suite_ok = False
    # A drifted lock is a red suite — the umbrella must not smooth a red lock
    # into "ok." ``matches=None`` (no lock file) is informational and does NOT
    # fail the suite: there's no baseline to compare against. ``matches=False``
    # (drift, or an unreadable lock) MUST fail the suite so that ``doctor`` and
    # ``lock --check`` agree on whether the lock is healthy.
    if lock_result.matches is False:
        suite_ok = False

    if memory_provider is not None:
        mp_ok = bool(memory_provider.get("ok", False))
        if mp_config.engine == "hindsight" and mp_config.endpoint and not mp_ok:
            suite_ok = False

    codex_health: CodexHealthReport | None = None
    if codex_health_checks:
        codex_catalog = (
            with_marketplace(CODEX_PLUGIN_CATALOG, codex_marketplace)
            if codex_marketplace is not None
            else CODEX_PLUGIN_CATALOG
        )
        codex_health = check_codex_health(
            runner=runner,
            installed=installed,
            catalog=codex_catalog,
            required_plugin_ids=frozenset({CodexPluginId.AGENT_NOTES, CodexPluginId.CAIRN}),
        )

    return SuiteReport(
        suite_ok=suite_ok,
        components=reports,
        lock=lock_result,
        post_restore=post_restore,
        key_rotation=key_rotation,
        store_growth=store_growth,
        profile_classification=profile_classification,
        memory_provider=memory_provider,
        codex_health=codex_health,
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )


def format_text(report: SuiteReport) -> str:
    """Human-readable summary for `doctor` without --json."""
    lines: list[str] = []
    for c in report.components:
        tag = f"[{c.tier.value.upper()}]"
        ver = f" v{c.version}" if c.version else ""
        detail = f"  {c.detail}" if c.detail else ""
        timing = f"  ({c.duration_ms:.0f}ms)" if c.duration_ms is not None else ""
        lines.append(f"  {c.component:<22} {tag:<10} {c.status.value:<15}{ver}{detail}{timing}")
    lines.append("")
    lines.append(lock.format_drift_text(report.lock))
    if report.post_restore is not None:
        lines.append("")
        lines.append("post-restore verification:")
        lines.append(verify_restore.format_text(report.post_restore))
    if report.key_rotation is not None:
        lines.append("")
        lines.append(key_watch.format_key_rotation_text(report.key_rotation))
    if report.store_growth is not None:
        lines.append("")
        lines.append(key_watch.format_store_growth_text(report.store_growth))
    if report.profile_classification is not None:
        cls = report.profile_classification
        lines.append("")
        lines.append("profile classification:")
        if cls.profile is not None:
            lines.append(f"  profile: {profile_label(cls.profile)}")
        else:
            lines.append("  profile: none (below Profile A)")
        missing = ", ".join(cls.missing_required) if cls.missing_required else "(none)"
        extra = ", ".join(cls.extra_optional) if cls.extra_optional else "(none)"
        lines.append(f"  missing required: {missing}")
        lines.append(f"  extra optional: {extra}")
    if report.memory_provider is not None:
        mp = report.memory_provider
        engine = str(mp.get("engine", "unknown"))
        mp_ok = bool(mp.get("ok", False))
        version = mp.get("version")
        ver = f" v{version}" if version else ""
        status = "ok" if mp_ok else "not ok"
        detail = str(mp.get("detail", ""))
        lines.append("")
        lines.append("memory provider:")
        lines.append(f"  engine: {engine}  {status}{ver}  {detail}".rstrip())
    if report.codex_health is not None:
        lines.append("")
        lines.append(format_codex_health_text(report.codex_health))
    total = f"  ({report.duration_ms:.0f}ms)" if report.duration_ms is not None else ""
    lines.append(f"suite: {'OK' if report.suite_ok else 'NOT OK'}{total}")
    return "\n".join(lines)
