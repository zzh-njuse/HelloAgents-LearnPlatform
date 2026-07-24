"""Stage 4 Slice 5 — Repair immutability regression tests (Codex review High 1).

These tests verify that ``_assert_repair_immutability`` correctly rejects
specialized repairs that attempt to change immutable fields (hidden_tests,
stem, citation_ids, public_examples, constraints, input_description,
output_description for coding; rubric for scientific).

The function is called before ``_merge_specialized_repair`` in the generation
path, so a provider that returns altered immutable fields causes the repair
to be rejected rather than silently accepted.

No provider, MCP, DB, or secrets are exercised.
"""

from __future__ import annotations

import pytest

from academic_companion.practice_agents import (
    PracticeItemArtifact,
    CodingTestCase,
    PracticeRubricCriterion,
)
from learn_platform_api.services.practice_generation import (
    _assert_repair_immutability,
)


def _coding_item(**overrides) -> PracticeItemArtifact:
    """Build a minimal coding item artifact for testing.

    The Python coding contract requires ``def solve(input_text):`` and
    3-20 hidden tests with unique inputs.
    """
    base = {
        "item_key": "c1",
        "item_type": "coding",
        "target_key": "objective_1",
        "language": "python",
        "stem": "Write a function that reverses a string.",
        "citation_ids": ["e1", "e2"],
        "reference_solution": "def solve(input_text): return input_text[::-1]",
        "starter_code": "def solve(input_text):\n    pass",
        "hidden_tests": [
            CodingTestCase(input="hello", expected_output="olleh"),
            CodingTestCase(input="abc", expected_output="cba"),
            CodingTestCase(input="123", expected_output="321"),
        ],
        "public_examples": [
            CodingTestCase(input="test", expected_output="tset"),
        ],
        "constraints": ["time_limit: 1s"],
        "input_description": "A string.",
        "output_description": "The reversed string.",
    }
    base.update(overrides)
    return PracticeItemArtifact.model_validate(base)


def _scientific_item(**overrides) -> PracticeItemArtifact:
    """Build a minimal scientific item artifact for testing."""
    base = {
        "item_key": "s1",
        "item_type": "scientific",
        "target_key": "objective_1",
        "stem": "Calculate the acceleration due to gravity.",
        "citation_ids": ["e1"],
        "reference_answer": "9.81 m/s^2",
        "rubric": [
            PracticeRubricCriterion(
                criterion_key="rk1",
                description="Correct numerical value",
                weight=50,
            ),
            PracticeRubricCriterion(
                criterion_key="rk2",
                description="Correct unit",
                weight=50,
            ),
        ],
        "scientific_answer_spec": {
            "normalized_answer": "9.81",
            "unit": "m/s^2",
            "equivalence_rule": "numeric_tolerance",
            "tolerance": 0.01,
            "needs_remote_verification": False,
        },
    }
    base.update(overrides)
    return PracticeItemArtifact.model_validate(base)


class TestCodingRepairImmutability:
    """Coding items: immutable fields are stem, citation_ids, hidden_tests,
    public_examples, constraints, input_description, output_description."""

    def test_identical_items_pass(self):
        original = _coding_item()
        repaired = _coding_item()
        _assert_repair_immutability(original, repaired)  # no raise

    def test_reference_solution_change_allowed(self):
        """Only the reference_solution may change in a specialized repair."""
        original = _coding_item()
        repaired = _coding_item(
            reference_solution="def solve(input_text): return ''.join(reversed(input_text))",
        )
        _assert_repair_immutability(original, repaired)  # no raise

    def test_starter_code_change_allowed(self):
        original = _coding_item()
        repaired = _coding_item(starter_code="def solve(input_text):\n    # TODO")
        _assert_repair_immutability(original, repaired)  # no raise

    def test_stem_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(stem="Write a function that sorts a list.")
        with pytest.raises(ValueError, match="specialized repair changed immutable field: stem"):
            _assert_repair_immutability(original, repaired)

    def test_citation_ids_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(citation_ids=["e1", "e3"])
        with pytest.raises(ValueError, match="specialized repair changed immutable field: citation_ids"):
            _assert_repair_immutability(original, repaired)

    def test_hidden_tests_change_rejected(self):
        original = _coding_item()
        # Provider tries to substitute easier hidden tests
        repaired = _coding_item(
            hidden_tests=[
                CodingTestCase(input="x", expected_output="x"),
                CodingTestCase(input="y", expected_output="y"),
                CodingTestCase(input="z", expected_output="z"),
            ],
        )
        with pytest.raises(ValueError, match="specialized repair changed immutable field: hidden_tests"):
            _assert_repair_immutability(original, repaired)

    def test_public_examples_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(
            public_examples=[
                CodingTestCase(input="ab", expected_output="ba"),
            ],
        )
        with pytest.raises(ValueError, match="specialized repair changed immutable field: public_examples"):
            _assert_repair_immutability(original, repaired)

    def test_constraints_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(constraints=["time_limit: 5s"])
        with pytest.raises(ValueError, match="specialized repair changed immutable field: constraints"):
            _assert_repair_immutability(original, repaired)

    def test_input_description_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(input_description="An integer.")
        with pytest.raises(ValueError, match="specialized repair changed immutable field: input_description"):
            _assert_repair_immutability(original, repaired)

    def test_output_description_change_rejected(self):
        original = _coding_item()
        repaired = _coding_item(output_description="The sorted list.")
        with pytest.raises(ValueError, match="specialized repair changed immutable field: output_description"):
            _assert_repair_immutability(original, repaired)


class TestScientificRepairImmutability:
    """Scientific items: immutable fields are stem, citation_ids, rubric."""

    def test_identical_items_pass(self):
        original = _scientific_item()
        repaired = _scientific_item()
        _assert_repair_immutability(original, repaired)  # no raise

    def test_reference_answer_change_allowed(self):
        original = _scientific_item()
        repaired = _scientific_item(reference_answer="9.807 m/s^2")
        _assert_repair_immutability(original, repaired)  # no raise

    def test_stem_change_rejected(self):
        original = _scientific_item()
        repaired = _scientific_item(stem="Calculate the speed of light.")
        with pytest.raises(ValueError, match="specialized repair changed immutable field: stem"):
            _assert_repair_immutability(original, repaired)

    def test_citation_ids_change_rejected(self):
        original = _scientific_item()
        repaired = _scientific_item(citation_ids=["e2"])
        with pytest.raises(ValueError, match="specialized repair changed immutable field: citation_ids"):
            _assert_repair_immutability(original, repaired)

    def test_rubric_change_rejected(self):
        original = _scientific_item()
        repaired = _scientific_item(
            rubric=[
                PracticeRubricCriterion(
                    criterion_key="rk1",
                    description="Different rubric description",
                    weight=10,
                ),
                PracticeRubricCriterion(
                    criterion_key="rk2",
                    description="Filler",
                    weight=90,
                ),
            ],
        )
        with pytest.raises(ValueError, match="specialized repair changed immutable field: rubric"):
            _assert_repair_immutability(original, repaired)
