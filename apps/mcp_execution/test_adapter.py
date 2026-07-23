"""Tests for the MCP execution adapter — Batch A focused tests.

Uses FakeExecutionBackend for all tests; no real backend needed.
"""

import pytest
from adapter import (
    ALLOWED_LANGUAGES,
    BackendUnavailableError,
    ExecutionAdapter,
    FakeExecutionBackend,
    InvalidToolResultError,
    RunCodeInput,
    RunCodeOutput,
    ExecutionStatus,
    INPUT_SCHEMA_HASH,
    JUDGE0_MAX_FILE_SIZE_KIB,
    OUTPUT_SCHEMA_HASH,
    JUDGE0_LANGUAGE_MAP,
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    TOOL_NAME,
    _truncate,
    validate_backend_result,
)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestRunCodeInput:
    def test_valid_python(self):
        inp = RunCodeInput(request_id="r1", language="python", source_code="print('hi')")
        assert inp.language == "python"

    def test_valid_java(self):
        inp = RunCodeInput(request_id="r1", language="java", source_code="class Main {}")
        assert inp.language == "java"

    def test_valid_cpp(self):
        inp = RunCodeInput(request_id="r1", language="cpp", source_code="int main() {}")
        assert inp.language == "cpp"

    def test_invalid_language_rejected(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="javascript", source_code="console.log('hi')")

    def test_invalid_language_rust_rejected(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="rust", source_code="fn main() {}")

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="python", source_code="x", timeout=30)

    def test_source_code_max_length(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="python", source_code="x" * 20001)

    def test_source_code_max_length_boundary(self):
        inp = RunCodeInput(request_id="r1", language="python", source_code="x" * 20000)
        assert len(inp.source_code) == 20000

    def test_stdin_max_length(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="python", source_code="x", stdin="y" * 8001)

    def test_stdin_max_length_boundary(self):
        inp = RunCodeInput(request_id="r1", language="python", source_code="x", stdin="y" * 8000)
        assert len(inp.stdin) == 8000

    def test_empty_source_code_rejected(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="r1", language="python", source_code="")

    def test_empty_request_id_rejected(self):
        with pytest.raises(Exception):
            RunCodeInput(request_id="", language="python", source_code="x")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

class TestRunCodeOutput:
    def test_valid_completed(self):
        out = RunCodeOutput(
            status=ExecutionStatus.completed,
            exit_code=0,
            compile_output="",
            stdout="hello\n",
            stderr="",
            duration_ms=100,
            runtime="judge0-lang-71",
            stdout_truncated=False,
            stderr_truncated=False,
        )
        assert out.status == "completed"

    def test_valid_compile_error(self):
        out = RunCodeOutput(
            status=ExecutionStatus.compile_error,
            exit_code=-1,
            compile_output="error: syntax",
            stdout="",
            stderr="",
            duration_ms=50,
            runtime="judge0-lang-62",
            stdout_truncated=False,
            stderr_truncated=False,
        )
        assert out.status == "compile_error"

    def test_negative_duration_rejected(self):
        with pytest.raises(Exception):
            RunCodeOutput(
                status=ExecutionStatus.completed,
                exit_code=0,
                compile_output="",
                stdout="",
                stderr="",
                duration_ms=-1,
                runtime="",
                stdout_truncated=False,
                stderr_truncated=False,
            )

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            RunCodeOutput(
                status="unknown",
                exit_code=0,
                compile_output="",
                stdout="",
                stderr="",
                duration_ms=100,
                runtime="",
                stdout_truncated=False,
                stderr_truncated=False,
            )

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            RunCodeOutput(
                status=ExecutionStatus.completed,
                exit_code=0,
                compile_output="",
                stdout="",
                stderr="",
                duration_ms=100,
                runtime="",
                stdout_truncated=False,
                stderr_truncated=False,
                internal_url="http://secret",
            )


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

class TestTruncation:
    def test_short_text_not_truncated(self):
        text, truncated = _truncate("hello")
        assert text == "hello"
        assert not truncated

    def test_exact_boundary_not_truncated(self):
        data = "x" * (32 * 1024)
        text, truncated = _truncate(data)
        assert not truncated

    def test_over_boundary_truncated(self):
        data = "x" * (32 * 1024 + 100)
        text, truncated = _truncate(data)
        assert truncated
        assert len(text.encode("utf-8")) <= 32 * 1024


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------

class TestValidateBackendResult:
    def test_valid_result_passes(self):
        raw = {
            "status": "completed",
            "exit_code": 0,
            "compile_output": "",
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 100,
            "runtime": "judge0-lang-71",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }
        result = validate_backend_result(raw)
        assert result.status == ExecutionStatus.completed

    def test_invalid_result_raises(self):
        raw = {"status": "unknown_status", "exit_code": 0}
        with pytest.raises(InvalidToolResultError):
            validate_backend_result(raw)

    def test_missing_field_raises(self):
        raw = {"status": "completed", "exit_code": 0}
        with pytest.raises(InvalidToolResultError):
            validate_backend_result(raw)


# ---------------------------------------------------------------------------
# Adapter readiness
# ---------------------------------------------------------------------------

class TestAdapterReadiness:
    def test_unconfigured_backend(self):
        adapter = ExecutionAdapter(backend_url=None)
        rd = adapter.readiness()
        assert rd["status"] == "unavailable"
        assert rd["configured"] is False
        assert rd["capability"] == "code_execution"
        assert rd["server_name"] == SERVER_NAME
        assert rd["protocol_version"] == MCP_PROTOCOL_VERSION
        assert rd["tool"] == TOOL_NAME
        assert rd["input_schema_hash"] == INPUT_SCHEMA_HASH
        assert rd["output_schema_hash"] == OUTPUT_SCHEMA_HASH
        assert set(rd["language_allowlist"]) == set(ALLOWED_LANGUAGES)

    def test_configured_backend(self):
        adapter = ExecutionAdapter(backend_url="http://judge0:2358")
        rd = adapter.readiness()
        assert rd["status"] == "ready"
        assert rd["configured"] is True


# ---------------------------------------------------------------------------
# Adapter execution — unconfigured
# ---------------------------------------------------------------------------

class TestAdapterExecutionUnconfigured:
    def test_run_code_raises_when_unconfigured(self):
        adapter = ExecutionAdapter(backend_url=None)
        inp = RunCodeInput(request_id="r1", language="python", source_code="print('hi')")
        with pytest.raises(BackendUnavailableError):
            adapter.run_code(inp)


class TestJudge0SandboxLimits:
    def test_compiler_file_limit_is_separate_from_response_limit(self):
        assert JUDGE0_MAX_FILE_SIZE_KIB == 1024
        huge = "x" * (32 * 1024 + 1000)
        truncated, was_truncated = _truncate(huge)
        assert was_truncated is True
        assert len(truncated.encode("utf-8")) <= 32 * 1024


# ---------------------------------------------------------------------------
# Fake backend
# ---------------------------------------------------------------------------

class TestFakeBackend:
    def test_judge0_accepted_response_without_optional_fields_is_normalized(self):
        class MinimalAcceptedBackend:
            def handle_submission(self, _payload):
                return {
                    "status": {"id": 3, "description": "Accepted"},
                    "stdout": "ok\n",
                    "stderr": None,
                    "compile_output": None,
                }

        adapter = ExecutionAdapter(_fake_backend=MinimalAcceptedBackend())
        result = adapter.run_code(RunCodeInput(
            request_id="minimal-accepted",
            language="python",
            source_code="print('ok')",
        ))

        assert result.status == ExecutionStatus.completed
        assert result.exit_code == 0
        assert result.runtime == "judge0-language-71"

    def test_python_success(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "print('hello world')",
            "language_id": 71,
            "stdin": "",
        })
        assert result["status"]["id"] == 3
        assert "hello world" in result["stdout"]

    def test_java_compile_error(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "COMPILE_ERROR class Main {}",
            "language_id": 62,
            "stdin": "",
        })
        assert result["status"]["id"] == 6

    def test_cpp_compile_error(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "COMPILE_ERROR int main()",
            "language_id": 54,
            "stdin": "",
        })
        assert result["status"]["id"] == 6

    def test_python_timeout(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "import time; time.sleep(999)",
            "language_id": 71,
            "stdin": "",
        })
        assert result["status"]["id"] == 5

    def test_java_timeout(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "while(true)",
            "language_id": 62,
            "stdin": "",
        })
        assert result["status"]["id"] == 5

    def test_python_runtime_error(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "1/0",
            "language_id": 71,
            "stdin": "",
        })
        assert result["status"]["id"] == 7

    def test_python_output_limit(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "huge_output",
            "language_id": 71,
            "stdin": "",
        })
        assert result["status"]["id"] == 8

    def test_python_with_stdin(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": "x = input()",
            "language_id": 71,
            "stdin": "hello",
        })
        assert result["status"]["id"] == 3
        assert "hello" in result["stdout"]

    def test_java_success(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": 'System.out.println("hello")',
            "language_id": 62,
            "stdin": "",
        })
        assert result["status"]["id"] == 3

    def test_cpp_success(self):
        fake = FakeExecutionBackend()
        result = fake.handle_submission({
            "source_code": 'cout << "hello"',
            "language_id": 54,
            "stdin": "",
        })
        assert result["status"]["id"] == 3


# ---------------------------------------------------------------------------
# Language mapping
# ---------------------------------------------------------------------------

class TestLanguageMapping:
    def test_all_allowed_languages_mapped(self):
        for lang in ALLOWED_LANGUAGES:
            assert lang in JUDGE0_LANGUAGE_MAP

    def test_python_maps_to_71(self):
        assert JUDGE0_LANGUAGE_MAP["python"] == 71

    def test_java_maps_to_62(self):
        assert JUDGE0_LANGUAGE_MAP["java"] == 62

    def test_cpp_maps_to_54(self):
        assert JUDGE0_LANGUAGE_MAP["cpp"] == 54


# ---------------------------------------------------------------------------
# Schema hashes are stable
# ---------------------------------------------------------------------------

class TestSchemaHashes:
    def test_input_schema_hash_nonempty(self):
        assert len(INPUT_SCHEMA_HASH) == 16

    def test_output_schema_hash_nonempty(self):
        assert len(OUTPUT_SCHEMA_HASH) == 16

    def test_hashes_are_different(self):
        assert INPUT_SCHEMA_HASH != OUTPUT_SCHEMA_HASH


# ---------------------------------------------------------------------------
# Protocol version
# ---------------------------------------------------------------------------

class TestProtocolVersion:
    def test_fixed_protocol_version(self):
        assert MCP_PROTOCOL_VERSION == "2025-11-25"
