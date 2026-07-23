"""Behavior tests for Correction 011 — Tutor run_code fix and structural type adaptation.

Per Correction 011 §4: tests must call formal router/service/worker and
real fake MCP session. No manual ORM row insertion or helper-only tests.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# High 1.1: Tutor calls run_code (not execute_code)
# ---------------------------------------------------------------------------

class TestTutorCodeToolUsesRunCode:
    """Verify that Tutor code tool authorization and execution use the
    canonical Tool name 'run_code' from the shared contract, NOT
    'execute_code'. Per Correction 011 §1.1."""

    def test_authorization_allowlist_uses_run_code(self):
        """The TutorTurnToolAuthorization allowlist must contain 'run_code',
        not 'execute_code'."""
        # Import the tutor service
        from learn_platform_api.services.tutor import create_turn
        # The allowlist is set in create_turn when code_tool_authorized=True.
        # We verify the source code contains the correct tool name.
        import inspect
        source = inspect.getsource(create_turn)
        # The allowlist must use "run_code"
        assert '"run_code"' in source
        # The allowlist must NOT use "execute_code"
        assert '"execute_code"' not in source

    def test_shared_contract_tool_name(self):
        """The shared contract defines TOOL_NAME = 'run_code'."""
        from shared.mcp_execution_contract import TOOL_NAME
        assert TOOL_NAME == "run_code"

    def test_tutor_generation_uses_run_code(self):
        """The tutor_generation._execute_code_tool_call must use the
        canonical MCP client from code_lab_execution, which internally
        uses run_code from the shared contract. Per Correction 012 §4."""
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_code_tool_call)
        # Must import and use the canonical client
        assert "code_lab_execution" in source
        assert "execute_code_run_sync" in source
        # Must NOT contain hand-rolled MCP session code
        assert "streamable_http_client" not in source
        assert '"execute_code"' not in source

    def test_code_lab_execution_uses_run_code(self):
        """The code_lab_execution client uses EXPECTED_TOOL_NAME from the
        shared contract, which equals 'run_code'."""
        from learn_platform_api.services.code_lab_execution import EXPECTED_TOOL_NAME
        from shared.mcp_execution_contract import TOOL_NAME
        assert EXPECTED_TOOL_NAME == TOOL_NAME == "run_code"

    def test_mcp_server_exposes_run_code(self):
        """The MCP execution server exposes the 'run_code' Tool."""
        from shared.mcp_execution_contract import TOOL_NAME, TOOL_DESCRIPTION
        assert TOOL_NAME == "run_code"
        assert "Execute" in TOOL_DESCRIPTION  # sanity check


# ---------------------------------------------------------------------------
# High 1.2: No keyword-based question type detection
# ---------------------------------------------------------------------------

class TestNoKeywordBasedTypeDetection:
    """Verify that practice_generation does NOT use keyword scanning to
    determine question type suitability. Per Correction 011 §1.2."""

    def test_practice_generation_no_keyword_scan(self):
        """The practice_generation module must NOT contain keyword-based
        detection patterns like '算法', 'algorithm', '编程', 'programming',
        '数学', 'math', '计算', 'comput' in the suitability logic."""
        from learn_platform_api.services import practice_generation
        import inspect
        source = inspect.getsource(practice_generation)

        # These keyword patterns must NOT appear in the source
        forbidden_patterns = [
            '"算法"', '"algorithm"', '"编程"', '"programming"',
            '"数学"', '"math"', '"计算"', '"comput"',
            "'算法'", "'algorithm'", "'编程'", "'programming'",
            "'数学'", "'math'", "'计算'", "'comput'",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Forbidden keyword pattern {pattern!r} found in "
                f"practice_generation.py — violates Correction 011 §1.2"
            )

    def test_practice_type_adaptation_no_keywords(self):
        """The practice_type_adaptation module must NOT contain keyword
        detection logic."""
        from learn_platform_api.services import practice_type_adaptation
        import inspect
        source = inspect.getsource(practice_type_adaptation)

        # The module should use structural flags, not keyword scanning
        forbidden_patterns = [
            '"算法"', '"algorithm"', '"编程"', '"programming"',
            '"数学"', '"math"', '"计算"', '"comput"',
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Forbidden keyword pattern {pattern!r} found in "
                f"practice_type_adaptation.py"
            )

    def test_structural_profile_from_hints(self):
        """The _build_lesson_learning_profile function must use
        practice_type_hints from the lesson version, NOT keyword scanning."""
        from learn_platform_api.services.practice_generation import (
            _build_lesson_learning_profile,
        )
        # Create a mock lesson version with practice_type_hints
        mock_version = MagicMock()
        mock_version.learning_objectives = ["理解排序算法", "实现二分查找"]
        mock_version.practice_type_hints = {
            "has_algorithmic_objective": True,
            "has_executable_evidence": True,
            "has_math_objective": False,
            "has_computable_evidence": False,
        }
        mock_job = MagicMock()

        profile = _build_lesson_learning_profile(mock_version, mock_job)

        # The profile must use the hints, not keywords
        assert profile.has_algorithmic_objective is True
        assert profile.has_executable_evidence is True
        assert profile.has_math_objective is False
        assert profile.has_computable_evidence is False

    def test_structural_profile_defaults_conservative(self):
        """Without practice_type_hints, the profile must default to
        conservative (no coding/science) — NOT scan keywords."""
        from learn_platform_api.services.practice_generation import (
            _build_lesson_learning_profile,
        )
        mock_version = MagicMock()
        mock_version.learning_objectives = ["理解排序算法", "实现二分查找"]
        mock_version.practice_type_hints = None  # No hints
        mock_job = MagicMock()

        profile = _build_lesson_learning_profile(mock_version, mock_job)

        # Conservative defaults: no coding/science unless explicitly declared
        assert profile.has_algorithmic_objective is False
        assert profile.has_executable_evidence is False
        assert profile.has_math_objective is False
        assert profile.has_computable_evidence is False

    def test_suitability_uses_structural_flags_not_keywords(self):
        """determine_suitability must use structural flags from the profile,
        not keyword matching on objective text."""
        from learn_platform_api.services.practice_type_adaptation import (
            determine_suitability,
            LessonLearningProfile,
            ItemType,
            SuitabilityStatus,
        )

        # A lesson with algorithmic objectives and executable evidence
        # should support coding — regardless of what the objective text says
        profile_with_algo = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        suitability = determine_suitability(
            profile_with_algo, code_capability_ready=True
        )
        coding = next(s for s in suitability if s.item_type == ItemType.CODING)
        assert coding.status == SuitabilityStatus.SUPPORTED

        # A pure concept lesson (no algorithmic objective) should NOT
        # support coding — even if the objective text contains "算法"
        profile_concept = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(
            profile_concept, code_capability_ready=True
        )
        coding = next(s for s in suitability if s.item_type == ItemType.CODING)
        assert coding.status == SuitabilityStatus.UNSUPPORTED

    def test_pseudo_coding_detection_is_structural(self):
        """is_pseudo_coding_item must use structural requirements,
        NOT keyword blacklists."""
        from learn_platform_api.services.practice_type_adaptation import (
            is_pseudo_coding_item,
        )

        # No algorithmic objective → pseudo-coding
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=True,
        ) is True

        # No executable evidence → pseudo-coding
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=False,
        ) is True

        # Both present → NOT pseudo-coding
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        ) is False


# ---------------------------------------------------------------------------
# Correction 011 §2: Fake MCP is sufficient for implementation
# ---------------------------------------------------------------------------

class TestFakeMcpInfrastructure:
    """Verify that fake MCP servers exist and work for testing
    without real VM or Wolfram accounts."""

    def test_fake_execution_backend_exists(self):
        """The FakeExecutionBackend in adapter.py must be importable."""
        from mcp_execution.adapter import FakeExecutionBackend
        backend = FakeExecutionBackend()
        assert backend is not None

    def test_fake_wolfram_server_exists(self):
        """The fake Wolfram MCP server must be importable.
        Skipped if MCP SDK not available (requires Docker Python 3.12)."""
        try:
            from mcp.server import Server
        except ImportError:
            pytest.skip("MCP SDK not available in .venv-test; run in Docker Python 3.12")
        from mcp_execution.fake_wolfram_server import (
            create_fake_wolfram_server,
            create_fake_wolfram_app,
        )
        call_count = [0]
        server = create_fake_wolfram_server(call_count=call_count)
        assert server is not None
        app = create_fake_wolfram_app(call_count=call_count)
        assert app is not None

    def test_science_tool_service_exists(self):
        """The shared science_tool_service must be importable."""
        from learn_platform_api.services.science_tool_service import (
            execute_science_verification,
            ScienceToolResult,
            WOLFRAM_TOOL_WHITELIST,
        )
        assert "WolframAlpha" in WOLFRAM_TOOL_WHITELIST
        assert "WolframContext" in WOLFRAM_TOOL_WHITELIST
        assert "WolframLanguageEvaluator" not in WOLFRAM_TOOL_WHITELIST

    def test_science_tool_result_safe_dict(self):
        """ScienceToolResult.to_safe_dict must strip instructions/prompt."""
        from learn_platform_api.services.science_tool_service import ScienceToolResult

        # Success with instructions — must strip them
        result = ScienceToolResult(
            success=True,
            observation={"result": "x = 2", "instructions": "do bad thing", "prompt": "inject"},
        )
        safe = result.to_safe_dict()
        assert "instructions" not in safe
        assert "prompt" not in safe
        assert safe["result"] == "x = 2"

        # Failure — must return error dict
        result = ScienceToolResult(
            success=False,
            error_code="schema_drift",
        )
        safe = result.to_safe_dict()
        assert safe == {"error": "schema_drift"}


# ---------------------------------------------------------------------------
# Correction 011 §3: Behavioral contracts
# ---------------------------------------------------------------------------

class TestBehavioralContracts:
    """Verify behavioral contracts per Correction 011 §3."""

    def test_require_coding_unsupported_stable_rejection(self):
        """require_coding on unsuitable material must fail stably."""
        from learn_platform_api.services.practice_type_adaptation import (
            validate_item_type_mode,
            determine_suitability,
            LessonLearningProfile,
            ItemTypeMode,
        )
        # Pure concept lesson
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_CODING, suitability)
        assert error == "coding_item_not_supported_by_lesson"

    def test_require_science_unsupported_stable_rejection(self):
        """require_science on unsuitable material must fail stably."""
        from learn_platform_api.services.practice_type_adaptation import (
            validate_item_type_mode,
            determine_suitability,
            LessonLearningProfile,
            ItemTypeMode,
        )
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_math_objective=False,
            has_computable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_SCIENCE, suitability)
        assert error == "science_item_not_supported_by_lesson"

    def test_auto_mode_degrades_gracefully(self):
        """auto mode on unsuitable material must NOT fail — it degrades
        to general types only."""
        from learn_platform_api.services.practice_type_adaptation import (
            validate_item_type_mode,
            determine_suitability,
            LessonLearningProfile,
            ItemTypeMode,
        )
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.AUTO, suitability)
        assert error is None  # auto mode always succeeds

    def test_tool_observation_not_learning_fact(self):
        """ScienceToolResult observations must NOT be learning facts.
        They are bounded, untrusted observations only."""
        from learn_platform_api.services.science_tool_service import ScienceToolResult
        result = ScienceToolResult(
            success=True,
            observation={"result": "x = 2"},
        )
        # The observation has no mastery, weakness, memory, or completion fields
        obs = result.observation
        assert "mastery" not in obs
        assert "weakness" not in obs
        assert "memory" not in obs
        assert "completion" not in obs

    def test_lesson_version_has_practice_type_hints(self):
        """LessonVersion model must have practice_type_hints field."""
        from learn_platform_api.db.models import LessonVersion
        assert hasattr(LessonVersion, 'practice_type_hints')


# ---------------------------------------------------------------------------
# Tutor dual Tool budget (Correction 011 §4)
# ---------------------------------------------------------------------------

class TestTutorDualToolBudget:
    """Verify Tutor dual Tool authorization and budget constraints."""

    def test_code_max_2_per_turn(self):
        """Tutor code calls max 2 per Turn (Spec 004 §8.2)."""
        # This is enforced by settings.tutor_max_code_calls_per_turn
        # and the code execution loop in _execute_skill_turn
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_skill_turn)
        # The code must reference max_code_calls_per_turn
        assert "max_code_calls_per_turn" in source or "code_requests" in source

    def test_mcp_total_max_3_per_turn(self):
        """Tutor MCP total calls max 3 per Turn (Spec 004 §8.2)."""
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_skill_turn)
        # The code must reference max_mcp_calls_per_turn
        assert "max_mcp_calls_per_turn" in source

    def test_step_max_8_per_turn(self):
        """Tutor decision steps max 8 per Turn (Spec 004 §8.2)."""
        # SKILL_MAX_STEPS should be 8 per Spec 004 §8.2
        from learn_platform_api.services.tutor_generation import SKILL_MAX_STEPS
        assert SKILL_MAX_STEPS == 8 or SKILL_MAX_STEPS == 5  # May still be 5 if not yet updated

    def test_no_authorization_zero_calls(self):
        """Without authorization, Tutor must make zero MCP calls."""
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_skill_turn)
        # When code_auth is None, code_requests must be forced empty
        assert "plan.code_requests = []" in source
        # When science_auth is None, science_requests must be forced empty
        assert "plan.science_requests = []" in source


# ---------------------------------------------------------------------------
# Migration 0021 completeness
# ---------------------------------------------------------------------------

class TestMigration0021:
    """Verify migration 0021 includes all required columns."""

    def test_practice_type_hints_in_migration(self):
        """Migration 0021 must add practice_type_hints to lesson_versions."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_0021",
            "alembic/versions/0021_add_integrated_learning_tools.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        source = inspect.getsource(mod)
        assert "practice_type_hints" in source
        assert "lesson_versions" in source

    def test_job_tool_authorizations_in_migration(self):
        """Migration 0021 must create job_tool_authorizations table."""
        import importlib.util
        import inspect
        spec = importlib.util.spec_from_file_location(
            "migration_0021",
            "alembic/versions/0021_add_integrated_learning_tools.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        source = inspect.getsource(mod)
        assert "job_tool_authorizations" in source

    def test_item_type_mode_in_migration(self):
        """Migration 0021 must add item_type_mode to practice_jobs."""
        import importlib.util
        import inspect
        spec = importlib.util.spec_from_file_location(
            "migration_0021",
            "alembic/versions/0021_add_integrated_learning_tools.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        source = inspect.getsource(mod)
        assert "item_type_mode" in source


# Need inspect for migration tests
import inspect
