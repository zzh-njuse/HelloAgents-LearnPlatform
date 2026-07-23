"""Product-owned execution MCP adapter.

Fixed Tool contract per Spec 004 §5.2 and ADR 006 §2.5:
- Tool: ``run_code``
- Input: ``{request_id, language, source_code, stdin}``
- Output: ``{status, exit_code, compile_output, stdout, stderr,
            duration_ms, runtime, stdout_truncated, stderr_truncated}``

The adapter connects to an administrator-configured execution backend URL.
If the backend is unavailable, readiness reports ``unavailable`` and new
calls are rejected — never silently degraded.

Per correction 004 §2: all canonical models and schema hashes come from
the shared contract package ``shared.mcp_execution_contract``. This module
does NOT duplicate Pydantic models or hand-write schemas.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

# Per correction 004 §2: import from the single canonical source.
# If this import fails, the MCP server cannot start — that is correct,
# never silently fall back to a local copy that may drift.
from shared.mcp_execution_contract import (
    ALLOWED_LANGUAGES,
    COMPILE_TIME_SECONDS,
    ExecutionStatus,
    INPUT_SCHEMA,
    INPUT_SCHEMA_HASH,
    OUTPUT_MAX_BYTES,
    OUTPUT_SCHEMA,
    OUTPUT_SCHEMA_HASH,
    RunCodeInput,
    RunCodeOutput,
    SERVER_NAME,
    SERVER_VERSION,
    SOURCE_CODE_MAX_CHARS,
    STDIN_MAX_CHARS,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    WALL_TIME_SECONDS,
    MCP_PROTOCOL_VERSION,
)

# Judge0's max_file_size limits compiler/runtime-created files, not captured
# stdout. Compiled Java/C++ artifacts routinely exceed the 32 KiB response
# ceiling, so keep a separate bounded sandbox-file allowance. Response fields
# are still truncated to OUTPUT_MAX_BYTES below.
JUDGE0_MAX_FILE_SIZE_KIB = 1024

logger = logging.getLogger("mcp_execution.adapter")


# ---------------------------------------------------------------------------
# Backend language mapping
# ---------------------------------------------------------------------------

# Map product language to Judge0 language_id (Spec 004 §5.2 / spike doc)
JUDGE0_LANGUAGE_MAP: dict[str, int] = {
    "python": 71,   # Python 3
    "java": 62,     # Java 11
    "cpp": 54,      # C++ GCC 9.2
}


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------

def _truncate(text: str, max_bytes: int = OUTPUT_MAX_BYTES) -> tuple[str, bool]:
    """Truncate text to max_bytes UTF-8, returning (truncated, was_truncated)."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated, True


# ---------------------------------------------------------------------------
# Result validation — re-validate backend output against fixed schema
# ---------------------------------------------------------------------------

class InvalidToolResultError(Exception):
    """Raised when the backend returns data that doesn't match the fixed schema."""


def validate_backend_result(raw: dict[str, Any]) -> RunCodeOutput:
    """Validate and normalize backend result against the fixed output contract.

    Maps unknown fields, illegal enum values, negative duration, or
    untruncated oversized output to ``invalid_tool_result``.
    """
    try:
        return RunCodeOutput.model_validate(raw)
    except Exception as exc:
        raise InvalidToolResultError(f"backend result schema violation: {exc}") from exc


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ExecutionAdapter:
    """Product-owned execution MCP adapter.

    Connects to an administrator-configured backend URL.
    All calls go through ``run_code`` with the fixed input/output contract.

    The backend_url must be explicitly configured by the administrator.
    If not configured, readiness reports unavailable and run_code raises
    BackendUnavailableError — never silently degrades or uses a fake backend.
    """

    def __init__(
        self,
        backend_url: str | None = None,
        timeout_seconds: float = 15.0,
        *,
        _fake_backend: "FakeExecutionBackend | None" = None,
    ):
        self._backend_url = backend_url
        self._timeout = timeout_seconds
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()
        # _fake_backend is ONLY for test injection — never used in production.
        self._fake_backend = _fake_backend

    # -- readiness --

    @property
    def backend_url(self) -> str | None:
        return self._backend_url

    def readiness(self) -> dict[str, Any]:
        """Check adapter readiness without calling the backend.

        Returns a capability snapshot for drift detection.
        """
        configured = self._backend_url is not None and len(self._backend_url) > 0
        return {
            "capability": "code_execution",
            "server_name": SERVER_NAME,
            "server_version": SERVER_VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "tool": TOOL_NAME,
            "input_schema_hash": INPUT_SCHEMA_HASH,
            "output_schema_hash": OUTPUT_SCHEMA_HASH,
            "language_allowlist": list(ALLOWED_LANGUAGES),
            "configured": configured,
            "status": "ready" if configured else "unavailable",
        }

    # -- execution --

    def run_code(self, inp: RunCodeInput) -> RunCodeOutput:
        """Execute code via the fixed backend contract.

        In production, calls the administrator-configured execution backend
        (Judge0/Piston native HTTP) which is only reachable from inside
        this MCP server — the product API/worker never calls Judge0 HTTP
        directly.

        If a _fake_backend was injected for testing, uses that instead.
        Otherwise, if no backend_url is configured, raises
        BackendUnavailableError — never silently degrades.

        Raises:
            BackendUnavailableError: backend URL not configured or unreachable.
            InvalidToolResultError: backend returned invalid result.
        """
        # Test-only fake backend path — must be explicitly injected
        if self._fake_backend is not None:
            return self._run_via_fake(inp)

        if not self._backend_url:
            raise BackendUnavailableError("execution backend URL not configured")

        return self._run_via_judge0(inp)

    def _run_via_fake(self, inp: RunCodeInput) -> RunCodeOutput:
        """Execute via injected fake backend — test only, never production."""
        assert self._fake_backend is not None  # guaranteed by run_code
        language_id = JUDGE0_LANGUAGE_MAP[inp.language]
        payload = {
            "source_code": inp.source_code,
            "language_id": language_id,
            "stdin": inp.stdin,
        }
        start = time.monotonic()
        raw = self._fake_backend.handle_submission(payload)
        return self._normalize_judge0_result(raw, start, language_id)

    def _run_via_judge0(self, inp: RunCodeInput) -> RunCodeOutput:
        """Execute via Judge0/Piston native HTTP — only inside this MCP server."""
        client = self._get_client()
        language_id = JUDGE0_LANGUAGE_MAP[inp.language]

        # Build Judge0-compatible submission payload
        payload = {
            "source_code": inp.source_code,
            "language_id": language_id,
            "stdin": inp.stdin,
            "cpu_time_limit": WALL_TIME_SECONDS,
            "wall_time_limit": WALL_TIME_SECONDS + 2,  # small buffer
            "memory_limit": 128_000,  # 128 MB in KB
            "max_file_size": JUDGE0_MAX_FILE_SIZE_KIB,
        }

        start = time.monotonic()
        try:
            response = client.post(
                f"{self._backend_url.rstrip('/')}/submissions",
                json=payload,
                params={"wait": "true", "base64_encoded": "false"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise BackendUnavailableError(f"execution backend unreachable: {exc}") from exc
        except httpx.TimeoutException as exc:
            return RunCodeOutput(
                status=ExecutionStatus.timed_out,
                exit_code=-1,
                compile_output="",
                stdout="",
                stderr="",
                duration_ms=int((time.monotonic() - start) * 1000),
                runtime="",
                stdout_truncated=False,
                stderr_truncated=False,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 502, 503, 504):
                raise BackendUnavailableError(f"execution backend temporary error: {exc.response.status_code}") from exc
            raise BackendUnavailableError(f"execution backend error: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise BackendUnavailableError("execution backend request failed") from exc

        try:
            raw_result = response.json()
        except ValueError as exc:
            raise InvalidToolResultError("execution backend returned invalid JSON") from exc
        if not isinstance(raw_result, dict):
            raise InvalidToolResultError("execution backend returned a non-object result")
        return self._normalize_judge0_result(raw_result, start, language_id)

    def _normalize_judge0_result(
        self,
        raw: dict[str, Any],
        start: float,
        language_id: int,
    ) -> RunCodeOutput:
        """Normalize Judge0 result into the fixed product output contract."""
        duration_ms = int((time.monotonic() - start) * 1000)

        # Judge0 status mapping
        status_id = raw.get("status", {}).get("id", 0)
        if status_id in (1, 2):  # In Queue / Processing — shouldn't reach here for sync
            raise InvalidToolResultError(f"unexpected in-progress status: {status_id}")

        if status_id == 13:
            raise BackendUnavailableError("execution backend internal error")

        status_map = {
            3: ExecutionStatus.completed,       # Accepted
            4: ExecutionStatus.runtime_error,   # Wrong Answer
            5: ExecutionStatus.timed_out,        # Time Limit Exceeded
            6: ExecutionStatus.compile_error,   # Compilation Error
            7: ExecutionStatus.runtime_error,   # Runtime Error (SIGSEGV etc.)
            8: ExecutionStatus.output_limited,  # Runtime Error (SIGXFSZ)
            9: ExecutionStatus.runtime_error,   # Runtime Error (SIGFPE)
            10: ExecutionStatus.runtime_error,  # Runtime Error (SIGABRT)
            11: ExecutionStatus.runtime_error,  # Runtime Error (NZEC)
            12: ExecutionStatus.runtime_error,  # Runtime Error (Other)
            14: ExecutionStatus.runtime_error,  # Exec Format Error
        }
        status = status_map.get(status_id, ExecutionStatus.runtime_error)

        compile_output = raw.get("compile_output") or ""
        stdout_raw = raw.get("stdout") or ""
        stderr_raw = raw.get("stderr") or ""
        raw_exit_code = raw.get("exit_code")
        # Judge0's synchronous response omits exit_code by default.  Accepted
        # is authoritative success, so expose the conventional zero instead of
        # a misleading -1.  Other outcomes remain unknown/non-zero as -1.
        exit_code = (
            0
            if status == ExecutionStatus.completed and raw_exit_code is None
            else (raw_exit_code if raw_exit_code is not None else -1)
        )

        stdout, stdout_truncated = _truncate(stdout_raw)
        stderr, stderr_truncated = _truncate(stderr_raw)
        compile_output, _ = _truncate(compile_output)

        result = RunCodeOutput(
            status=status,
            exit_code=exit_code,
            compile_output=compile_output,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            runtime=f"judge0-language-{language_id}",
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        return result

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _get_client(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.Client()
            return self._client


class BackendUnavailableError(Exception):
    """Raised when the execution backend is not configured or unreachable."""


# ---------------------------------------------------------------------------
# Fake backend for offline testing
# ---------------------------------------------------------------------------

class FakeExecutionBackend:
    """In-process fake execution backend for offline tests.

    Simulates the Judge0 API contract without Docker or real execution.
    Supports Python/Java/C++ with deterministic outputs for test cases.
    """

    def handle_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process a Judge0-style submission and return a result dict."""
        language_id = payload.get("language_id", 0)
        source_code = payload.get("source_code", "")
        stdin_data = payload.get("stdin", "")

        # Simulate compile error for Java/C++ with syntax errors
        if language_id in (62, 54):  # Java, C++
            if "COMPILE_ERROR" in source_code:
                return {
                    "status": {"id": 6, "description": "Compilation Error"},
                    "compile_output": "error: syntax error",
                    "stdout": None,
                    "stderr": None,
                    "exit_code": None,
                    "language_id": language_id,
                }

        # Simulate timeout
        if "import time; time.sleep(999)" in source_code or "while(true)" in source_code:
            return {
                "status": {"id": 5, "description": "Time Limit Exceeded"},
                "compile_output": None,
                "stdout": None,
                "stderr": None,
                "exit_code": None,
                "language_id": language_id,
            }

        # Simulate output limit exceeded
        if "huge_output" in source_code:
            huge = "x" * (OUTPUT_MAX_BYTES + 1000)
            return {
                "status": {"id": 8, "description": "Output Limit Exceeded"},
                "compile_output": None,
                "stdout": huge,
                "stderr": None,
                "exit_code": None,
                "language_id": language_id,
            }

        # Simulate runtime error
        if "raise RuntimeError" in source_code or "1/0" in source_code:
            return {
                "status": {"id": 7, "description": "Runtime Error"},
                "compile_output": None,
                "stdout": None,
                "stderr": "RuntimeError: division by zero" if "1/0" in source_code else "RuntimeError",
                "exit_code": 1,
                "language_id": language_id,
            }

        # Normal execution — Python
        if language_id == 71:
            output = self._simulate_python(source_code, stdin_data)
            return {
                "status": {"id": 3, "description": "Accepted"},
                "compile_output": None,
                "stdout": output,
                "stderr": None,
                "exit_code": 0,
                "language_id": language_id,
            }

        # Normal execution — Java
        if language_id == 62:
            output = self._simulate_java(source_code, stdin_data)
            return {
                "status": {"id": 3, "description": "Accepted"},
                "compile_output": None,
                "stdout": output,
                "stderr": None,
                "exit_code": 0,
                "language_id": language_id,
            }

        # Normal execution — C++
        if language_id == 54:
            output = self._simulate_cpp(source_code, stdin_data)
            return {
                "status": {"id": 3, "description": "Accepted"},
                "compile_output": None,
                "stdout": output,
                "stderr": None,
                "exit_code": 0,
                "language_id": language_id,
            }

        # Unknown language
        return {
            "status": {"id": 6, "description": "Compilation Error"},
            "compile_output": f"error: unsupported language_id {language_id}",
            "stdout": None,
            "stderr": None,
            "exit_code": None,
            "language_id": language_id,
        }

    def _simulate_python(self, source: str, stdin_data: str) -> str:
        # Simple simulation for common patterns
        if "print(" in source:
            # Extract simple print content
            import re
            prints = re.findall(r'print\(["\'](.+?)["\']\)', source)
            if prints:
                return "\n".join(prints) + "\n"
        if stdin_data:
            return f"stdin received: {stdin_data}\n"
        return "ok\n"

    def _simulate_java(self, source: str, stdin_data: str) -> str:
        if "System.out.println" in source:
            import re
            prints = re.findall(r'System\.out\.println\(["\'](.+?)["\']\)', source)
            if prints:
                return "\n".join(prints) + "\n"
        return "ok\n"

    def _simulate_cpp(self, source: str, stdin_data: str) -> str:
        if "cout" in source:
            import re
            prints = re.findall(r'cout\s*<<\s*["\'](.+?)["\']', source)
            if prints:
                return "\n".join(prints) + "\n"
        return "ok\n"
