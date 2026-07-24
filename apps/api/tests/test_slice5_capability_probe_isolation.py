from __future__ import annotations

import threading
import time
from pathlib import Path

import yaml


def test_slow_science_probe_does_not_block_execution_refresh(monkeypatch) -> None:
    from learn_platform_api import capability_probe

    execution_writes: list[float] = []
    science_started = threading.Event()
    release_science = threading.Event()

    monkeypatch.setattr(capability_probe, "_shutdown", False)
    monkeypatch.setattr(capability_probe, "PROBE_INTERVAL_SECONDS", 0.02)

    def probe_execution() -> dict:
        return {"status": "ready", "detail": "ok", "verified_schema_hash": "hash"}

    def probe_science() -> dict:
        science_started.set()
        release_science.wait(timeout=1)
        return {"status": "ready", "detail": "ok", "verified_schema_hash": "hash"}

    def write_projection(_db, capability_id: str, _result: dict) -> None:
        if capability_id == "code_execution":
            execution_writes.append(time.monotonic())

    class FakeSession:
        def __init__(self, _engine) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def commit(self) -> None:
            pass

    monkeypatch.setattr(capability_probe, "Session", FakeSession)
    monkeypatch.setattr(capability_probe, "write_projection", write_projection)

    execution_thread = threading.Thread(
        target=capability_probe._run_capability_loop,
        args=(object(), "code_execution", probe_execution),
        daemon=True,
    )
    science_thread = threading.Thread(
        target=capability_probe._run_capability_loop,
        args=(object(), "science_computation", probe_science),
        daemon=True,
    )
    execution_thread.start()
    science_thread.start()

    try:
        assert science_started.wait(timeout=0.5)
        deadline = time.monotonic() + 0.5
        while len(execution_writes) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(execution_writes) >= 3
    finally:
        capability_probe._shutdown = True
        release_science.set()
        execution_thread.join(timeout=0.5)
        science_thread.join(timeout=0.5)


def test_api_receives_internal_execution_capability_identity() -> None:
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    api_environment = compose["services"]["api"]["environment"]
    assert api_environment["MCP_EXECUTION_ADAPTER_URL"] == (
        "${MCP_EXECUTION_ADAPTER_URL:-http://mcp-execution:8100}"
    )


def test_slow_failed_probe_waits_after_completion(monkeypatch) -> None:
    from learn_platform_api import capability_probe

    calls: list[float] = []

    class FakeSession:
        def __init__(self, _engine) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

    def failing_probe() -> dict:
        calls.append(time.monotonic())
        time.sleep(0.03)
        if len(calls) >= 2:
            capability_probe._shutdown = True
        raise RuntimeError("expected")

    monkeypatch.setattr(capability_probe, "_shutdown", False)
    monkeypatch.setattr(capability_probe, "PROBE_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(capability_probe, "Session", FakeSession)

    thread = threading.Thread(
        target=capability_probe._run_capability_loop,
        args=(object(), "science_computation", failing_probe),
        daemon=True,
    )
    thread.start()
    try:
        thread.join(timeout=0.5)
        assert not thread.is_alive()
        assert len(calls) == 2
        assert calls[1] - calls[0] >= 0.045
    finally:
        capability_probe._shutdown = True
        thread.join(timeout=0.5)
