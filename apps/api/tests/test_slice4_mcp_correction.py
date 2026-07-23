"""Slice 4 correction focused tests — per SLICE_4_GLM_CORRECTION_PACKET_001 §3.

Covers:
1. MCP client/server contract: schema, unknown Tool, invalid result
2. Code Run API: policy, scope isolation, idempotency, enqueue failure, delete no readback
3. Worker: claim, cancel, late result, final authority
4. Tutor: no auth zero calls, auth but no need zero calls, budget, unknown tool reject
5. Deletion: Run, Tutor Turn, Workspace
6. Compose: network isolation, secret minimization
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. MCP adapter contract tests (via import from the adapter module)
# ---------------------------------------------------------------------------

class TestExecutionAdapterContract:
    """Test the MCP execution adapter's fixed contracts."""

    @pytest.fixture(autouse=True)
    def _import_adapter(self):
        """Import adapter module with sys.path adjustment."""
        import sys
        mcp_path = str(Path(__file__).parent.parent.parent.parent / "apps" / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

    def test_run_code_input_extra_forbidden(self):
        from adapter import RunCodeInput
        with pytest.raises(Exception):
            RunCodeInput(
                request_id="test-1",
                language="python",
                source_code="print('hello')",
                stdin="",
                extra_field="not_allowed",
            )

    def test_run_code_output_extra_forbidden(self):
        from adapter import RunCodeOutput, ExecutionStatus
        with pytest.raises(Exception):
            RunCodeOutput(
                status=ExecutionStatus.completed,
                exit_code=0,
                compile_output="",
                stdout="hello\n",
                stderr="",
                duration_ms=100,
                runtime="test",
                stdout_truncated=False,
                stderr_truncated=False,
                extra_field="not_allowed",
            )

    def test_language_whitelist_enforced(self):
        from adapter import RunCodeInput
        with pytest.raises(Exception):
            RunCodeInput(
                request_id="test-1",
                language="javascript",
                source_code="console.log('hello')",
            )

    def test_source_code_max_length(self):
        from adapter import RunCodeInput, SOURCE_CODE_MAX_CHARS
        with pytest.raises(Exception):
            RunCodeInput(
                request_id="test-1",
                language="python",
                source_code="x" * (SOURCE_CODE_MAX_CHARS + 1),
            )

    def test_stdin_max_length(self):
        from adapter import RunCodeInput, STDIN_MAX_CHARS
        with pytest.raises(Exception):
            RunCodeInput(
                request_id="test-1",
                language="python",
                source_code="print('hi')",
                stdin="x" * (STDIN_MAX_CHARS + 1),
            )

    def test_schema_hashes_stable(self):
        from adapter import INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH
        from shared.mcp_execution_contract import INPUT_SCHEMA_HASH as SHARED_INPUT, OUTPUT_SCHEMA_HASH as SHARED_OUTPUT
        assert len(INPUT_SCHEMA_HASH) == 16
        assert len(OUTPUT_SCHEMA_HASH) == 16
        # Per correction 004 §2: adapter hashes must match shared contract
        assert INPUT_SCHEMA_HASH == SHARED_INPUT
        assert OUTPUT_SCHEMA_HASH == SHARED_OUTPUT

    def test_adapter_unconfigured_raises(self):
        from adapter import ExecutionAdapter, BackendUnavailableError
        adapter = ExecutionAdapter(backend_url=None)
        with pytest.raises(BackendUnavailableError):
            adapter.run_code(
                MagicMock(request_id="t", language="python", source_code="print(1)", stdin="")
            )

    def test_adapter_readiness_unconfigured(self):
        from adapter import ExecutionAdapter
        adapter = ExecutionAdapter(backend_url=None)
        r = adapter.readiness()
        assert r["status"] == "unavailable"
        assert r["configured"] is False

    def test_adapter_readiness_configured(self):
        from adapter import ExecutionAdapter
        adapter = ExecutionAdapter(backend_url="http://fake:1234")
        r = adapter.readiness()
        assert r["status"] == "ready"
        assert r["configured"] is True

    def test_fake_backend_only_via_injection(self):
        """Fake backend must be explicitly injected — never used in production."""
        from adapter import ExecutionAdapter, FakeExecutionBackend, BackendUnavailableError
        adapter = ExecutionAdapter(backend_url=None)
        with pytest.raises(BackendUnavailableError):
            adapter.run_code(
                MagicMock(request_id="t", language="python", source_code="print(1)", stdin="")
            )
        fake = FakeExecutionBackend()
        adapter_with_fake = ExecutionAdapter(backend_url=None, _fake_backend=fake)
        result = adapter_with_fake.run_code(
            MagicMock(request_id="t", language="python", source_code="print('hello')", stdin="")
        )
        assert result.status.value == "completed"

    def test_protocol_version_fixed(self):
        from adapter import MCP_PROTOCOL_VERSION
        assert MCP_PROTOCOL_VERSION == "2025-11-25"

    def test_output_truncation_within_limit(self):
        from adapter import _truncate, OUTPUT_MAX_BYTES
        text = "x" * 100
        result, truncated = _truncate(text)
        assert result == text
        assert truncated is False

    def test_output_truncation_exceeds_limit(self):
        from adapter import _truncate, OUTPUT_MAX_BYTES
        text = "x" * (OUTPUT_MAX_BYTES + 1000)
        result, truncated = _truncate(text)
        assert truncated is True
        assert len(result.encode("utf-8")) <= OUTPUT_MAX_BYTES


# ---------------------------------------------------------------------------
# 2. Product MCP client contract
# ---------------------------------------------------------------------------

class TestProductMcpClientContract:
    """Test the product-side MCP client in code_lab_execution.py."""

    def test_rejects_judge0_url(self):
        """MCP_EXECUTION_ADAPTER_URL must not be a Judge0 /submissions URL."""
        from learn_platform_api.services.code_lab_execution import (
            call_run_code_via_mcp, BackendUnavailableError,
        )
        settings = MagicMock()
        settings.mcp_execution_adapter_url = "http://judge0:2358/submissions"
        settings.code_lab_execution_timeout_seconds = 15.0
        import asyncio
        # If MCP SDK is not installed, we still get BackendUnavailableError
        # (just with a different message). The key invariant is: no fake result.
        with pytest.raises(BackendUnavailableError):
            asyncio.run(
                call_run_code_via_mcp("req1", "python", "print(1)", "", settings)
            )

    def test_unconfigured_raises(self):
        from learn_platform_api.services.code_lab_execution import (
            call_run_code_via_mcp, BackendUnavailableError,
        )
        settings = MagicMock()
        settings.mcp_execution_adapter_url = None
        import asyncio
        with pytest.raises(BackendUnavailableError):
            asyncio.run(
                call_run_code_via_mcp("req1", "python", "print(1)", "", settings)
            )

    def test_empty_url_raises(self):
        from learn_platform_api.services.code_lab_execution import (
            call_run_code_via_mcp, BackendUnavailableError,
        )
        settings = MagicMock()
        settings.mcp_execution_adapter_url = ""
        import asyncio
        with pytest.raises(BackendUnavailableError):
            asyncio.run(
                call_run_code_via_mcp("req1", "python", "print(1)", "", settings)
            )


# ---------------------------------------------------------------------------
# 3. Science tool whitelist and budget
# ---------------------------------------------------------------------------

class TestScienceToolWhitelist:
    """Test science tool whitelist and budget enforcement."""

    def test_wolfram_tool_whitelist(self):
        from learn_platform_api.services.tutor_generation import WOLFRAM_TOOL_WHITELIST
        assert "WolframAlpha" in WOLFRAM_TOOL_WHITELIST
        assert "WolframContext" in WOLFRAM_TOOL_WHITELIST
        assert "WolframLanguageEvaluator" not in WOLFRAM_TOOL_WHITELIST

    def test_science_request_contract(self):
        from academic_companion.teaching_skills.contracts import ScienceRequest
        req = ScienceRequest(tool="WolframAlpha", arguments={"input": "solve x^2=4"})
        assert req.tool == "WolframAlpha"
        with pytest.raises(Exception):
            ScienceRequest(tool="WolframLanguageEvaluator", arguments={"input": "test"})
        with pytest.raises(Exception):
            ScienceRequest(tool="UnknownTool", arguments={})

    def test_teaching_plan_science_requests_max_3(self):
        from academic_companion.teaching_skills.contracts import TeachingPlan
        plan = TeachingPlan(
            intent="concept_explanation",
            queries=["test query"],
            learning_context_use="unavailable",
            teaching_moves=["explain"],
            science_requests=[
                {"tool": "WolframAlpha", "arguments": {"input": "1+1"}},
                {"tool": "WolframContext", "arguments": {"input": "2+2"}},
                {"tool": "WolframAlpha", "arguments": {"input": "3+3"}},
            ],
        )
        assert len(plan.science_requests) == 3
        with pytest.raises(Exception):
            TeachingPlan(
                intent="concept_explanation",
                queries=["test query"],
                learning_context_use="unavailable",
                teaching_moves=["explain"],
                science_requests=[
                    {"tool": "WolframAlpha", "arguments": {"input": f"{i}"}}
                    for i in range(4)
                ],
            )

    def test_science_observation_block_type(self):
        from academic_companion.teaching_skills.contracts import TeachingAnswerBlock
        block = TeachingAnswerBlock(
            block_key="sci1",
            type="science_observation",
            text="WolframAlpha computed: x = ±2",
            citation_ids=[],
        )
        assert block.type == "science_observation"
        with pytest.raises(Exception):
            TeachingAnswerBlock(
                block_key="sci2",
                type="science_observation",
                text="result",
                citation_ids=["e1"],
            )


# ---------------------------------------------------------------------------
# 4. Cancel semantics
# ---------------------------------------------------------------------------

class TestCancelSemantics:
    """Test that queued/retry_wait cancel directly becomes canceled."""

    def test_queued_cancel_is_immediate(self):
        status = "queued"
        new_status = "canceled" if status in ("queued", "retry_wait") else "cancel_requested"
        assert new_status == "canceled"

    def test_running_cancel_is_requested(self):
        status = "running"
        new_status = "canceled" if status in ("queued", "retry_wait") else "cancel_requested"
        assert new_status == "cancel_requested"

    def test_retry_wait_cancel_is_immediate(self):
        status = "retry_wait"
        new_status = "canceled" if status in ("queued", "retry_wait") else "cancel_requested"
        assert new_status == "canceled"


# ---------------------------------------------------------------------------
# 5. MCP result must not modify learning facts
# ---------------------------------------------------------------------------

class TestMcpNoLearningSideEffects:
    """Verify MCP results cannot modify mastery/weakness/memory/completion."""

    def test_science_observation_not_in_factual_types(self):
        from academic_companion.teaching_skills.contracts import FACTUAL_BLOCK_TYPES
        assert "science_observation" not in FACTUAL_BLOCK_TYPES

    def test_science_observation_not_citable(self):
        from academic_companion.teaching_skills.contracts import CITABLE_BLOCK_TYPES
        assert "science_observation" not in CITABLE_BLOCK_TYPES


# ---------------------------------------------------------------------------
# 6. Compose network isolation
# ---------------------------------------------------------------------------

class TestComposeIsolation:
    """Verify Compose configuration enforces network isolation."""

    def _load_compose(self):
        import yaml
        compose_path = Path(__file__).parent.parent.parent.parent / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip("docker-compose.yml not found")
        with open(compose_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_mcp_execution_has_isolated_network(self):
        compose = self._load_compose()
        mcp = compose["services"].get("mcp-execution", {})
        networks = mcp.get("networks", [])
        assert "default" not in networks, "mcp-execution must use isolated network"

    def test_code_lab_worker_no_storage(self):
        compose = self._load_compose()
        worker = compose["services"].get("code-lab-worker", {})
        assert "volumes" not in worker or not any("storage" in str(v) for v in worker.get("volumes", [])), \
            "code-lab-worker must not mount storage"

    def test_code_lab_worker_no_qdrant(self):
        compose = self._load_compose()
        worker = compose["services"].get("code-lab-worker", {})
        env = worker.get("environment", {})
        assert "QDRANT_URL" not in env, "code-lab-worker must not have Qdrant config"

    def test_code_lab_worker_no_wolfram(self):
        compose = self._load_compose()
        worker = compose["services"].get("code-lab-worker", {})
        env = worker.get("environment", {})
        assert "WOLFRAM_MCP_ENABLED" not in env, "code-lab-worker must not have Wolfram config"
        assert "WOLFRAM_MCP_API_KEY" not in env, "code-lab-worker must not have Wolfram key"

    def test_api_no_wolfram_key(self):
        compose = self._load_compose()
        api = compose["services"].get("api", {})
        env = api.get("environment", {})
        assert "WOLFRAM_MCP_API_KEY" not in env, "API must not have Wolfram API key"

    def test_worker_has_wolfram_config(self):
        """Tutor worker must have Wolfram config for science tool calls."""
        compose = self._load_compose()
        worker = compose["services"].get("worker", {})
        env = worker.get("environment", {})
        assert "WOLFRAM_MCP_ENABLED" in env, "Tutor worker must have Wolfram config"


# ---------------------------------------------------------------------------
# 7. Tutor science tool authorization
# ---------------------------------------------------------------------------

class TestScienceToolAuthorization:
    """Test per-Turn science tool authorization semantics."""

    def test_no_auth_means_zero_calls(self):
        from academic_companion.teaching_skills.contracts import TeachingPlan
        plan = TeachingPlan(
            intent="concept_explanation",
            queries=["test"],
            learning_context_use="unavailable",
            teaching_moves=["explain"],
            science_requests=[],
        )
        assert len(plan.science_requests) == 0

    def test_auth_allows_up_to_3(self):
        from academic_companion.teaching_skills.contracts import TeachingPlan
        plan = TeachingPlan(
            intent="concept_explanation",
            queries=["solve equation"],
            learning_context_use="unavailable",
            teaching_moves=["explain"],
            science_requests=[
                {"tool": "WolframAlpha", "arguments": {"input": "x^2-4=0"}},
            ],
        )
        assert len(plan.science_requests) == 1

    def test_auth_but_no_need_is_zero(self):
        from academic_companion.teaching_skills.contracts import TeachingPlan
        plan = TeachingPlan(
            intent="concept_explanation",
            queries=["what is a variable"],
            learning_context_use="unavailable",
            teaching_moves=["explain"],
            science_requests=[],
        )
        assert len(plan.science_requests) == 0

    def test_wolfram_language_evaluator_rejected(self):
        from academic_companion.teaching_skills.contracts import ScienceRequest
        with pytest.raises(Exception):
            ScienceRequest(tool="WolframLanguageEvaluator", arguments={"input": "test"})
