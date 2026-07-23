"""
Practice type adaptation — determines which item types a lesson can support.

Per Spec 004 §6.2 and ADR 006 §2.6:
- Each candidate type gets supported|unsupported with objective/evidence mapping
- Coding requires evidence of algorithmic/programmatic/executable skills
- Scientific requires evidence of computable/symbolic/chemical targets
- Pure concept lessons never get coding/science items
- Type suitability is a structural, content-agnostic contract
- Not based on course name, keywords, or fixed blacklists

This module is in the domain layer and does NOT connect to databases or MCP.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ItemType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    SHORT_ANSWER = "short_answer"
    CODING = "coding"
    SCIENTIFIC = "scientific"


class SuitabilityStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ItemTypeMode(str, Enum):
    AUTO = "auto"
    GENERAL_ONLY = "general_only"
    REQUIRE_CODING = "require_coding"
    REQUIRE_SCIENCE = "require_science"


@dataclass(frozen=True)
class PracticeSuitability:
    """Suitability result for one candidate item type."""
    item_type: ItemType
    status: SuitabilityStatus
    objective_key: str | None = None
    evidence_keys: list[str] | None = None
    reason: str = ""


@dataclass(frozen=True)
class LessonLearningProfile:
    """
    Structured profile of a lesson's learning targets and evidence.
    Used to determine which practice item types are suitable.

    This is extracted from the lesson version's learning_objectives
    and evidence ledger — not from the course name or keywords.
    """
    # Learning objective keys from the lesson
    objective_keys: list[str]
    # Evidence keys available for this lesson
    evidence_keys: list[str]
    # Whether any objective involves algorithmic/programmatic/executable skills
    has_algorithmic_objective: bool = False
    # Whether any objective involves mathematical computation
    has_math_objective: bool = False
    # Whether any objective involves physical computation/relationships
    has_physics_objective: bool = False
    # Whether any objective involves chemical computation/reactions
    has_chemistry_objective: bool = False
    # Whether any evidence supports executable code verification
    has_executable_evidence: bool = False
    # Whether any evidence supports numerical/symbolic computation
    has_computable_evidence: bool = False
    # Evidence keys that map to algorithmic objectives
    algorithmic_evidence_keys: list[str] | None = None
    # Evidence keys that map to computable objectives
    computable_evidence_keys: list[str] | None = None


# ---------------------------------------------------------------------------
# Structural anti-pattern detection
# ---------------------------------------------------------------------------

# These are structural patterns that indicate a pseudo-coding item
# (not a real programming exercise). Per Spec 004 §6.2:
# "打印某概念关键词", "把段落复制到字符串", "为纯概念事实套空程序"
# We check structure, NOT course names or keyword blacklists.

PSEUDO_CODING_INDICATORS = {
    # A coding item that only prints a fixed string (no input/output contract)
    "no_io_contract",
    # A coding item where the "solution" is just string concatenation
    "string_concat_only",
    # A coding item with no deterministic assertions
    "no_deterministic_assertion",
    # A coding item that doesn't test any executable skill
    "no_executable_skill",
}


def is_pseudo_coding_item(
    objective_keys: list[str],
    evidence_keys: list[str],
    has_algorithmic_objective: bool,
    has_executable_evidence: bool,
) -> bool:
    """
    Determine if a coding item would be a pseudo-coding item
    (not a real programming exercise).

    Per Spec 004 §6.2: coding items must have evidence of
    algorithmic/programmatic/data-processing/computational skills
    with deterministic assertions. Pure concept material must not
    be forced into coding items.

    This uses structural requirements, NOT course name/keyword blacklists.
    """
    if not has_algorithmic_objective:
        return True  # No algorithmic objective = pseudo-coding
    if not has_executable_evidence:
        return True  # No executable evidence = pseudo-coding
    if not objective_keys:
        return True  # No objectives at all = pseudo-coding
    return False


# ---------------------------------------------------------------------------
# Suitability determination
# ---------------------------------------------------------------------------

def determine_suitability(
    profile: LessonLearningProfile,
    *,
    code_capability_ready: bool = False,
    science_capability_ready: bool = False,
) -> list[PracticeSuitability]:
    """
    Determine suitability for all candidate item types given a lesson profile.

    Per Spec 004 §6.2 and ADR 006 §2.6:
    - single_choice and short_answer are always supported (general types)
    - coding requires algorithmic objective + executable evidence + capability
    - scientific requires computable objective + computable evidence + capability
    - Pure concept lessons get zero coding/science suitability
    """
    results: list[PracticeSuitability] = []

    # General types are always supported
    results.append(PracticeSuitability(
        item_type=ItemType.SINGLE_CHOICE,
        status=SuitabilityStatus.SUPPORTED,
        objective_key=profile.objective_keys[0] if profile.objective_keys else None,
        evidence_keys=profile.evidence_keys[:3] if profile.evidence_keys else None,
        reason="Single choice is always supported for any lesson",
    ))
    results.append(PracticeSuitability(
        item_type=ItemType.SHORT_ANSWER,
        status=SuitabilityStatus.SUPPORTED,
        objective_key=profile.objective_keys[0] if profile.objective_keys else None,
        evidence_keys=profile.evidence_keys[:3] if profile.evidence_keys else None,
        reason="Short answer is always supported for any lesson",
    ))

    # Coding suitability
    pseudo = is_pseudo_coding_item(
        profile.objective_keys,
        profile.evidence_keys,
        profile.has_algorithmic_objective,
        profile.has_executable_evidence,
    )
    if pseudo or not code_capability_ready:
        results.append(PracticeSuitability(
            item_type=ItemType.CODING,
            status=SuitabilityStatus.UNSUPPORTED,
            reason=(
                "Lesson lacks algorithmic/executable learning objectives"
                if pseudo
                else "Code execution capability not ready"
            ),
        ))
    else:
        algo_evidence = profile.algorithmic_evidence_keys or profile.evidence_keys[:3]
        results.append(PracticeSuitability(
            item_type=ItemType.CODING,
            status=SuitabilityStatus.SUPPORTED,
            objective_key=profile.objective_keys[0],
            evidence_keys=algo_evidence,
            reason="Lesson has algorithmic objectives with executable evidence",
        ))

    # Scientific suitability
    has_computable = (
        profile.has_math_objective
        or profile.has_physics_objective
        or profile.has_chemistry_objective
    )
    if (
        not profile.objective_keys
        or not has_computable
        or not profile.has_computable_evidence
        or not science_capability_ready
    ):
        results.append(PracticeSuitability(
            item_type=ItemType.SCIENTIFIC,
            status=SuitabilityStatus.UNSUPPORTED,
            reason=(
                "Lesson lacks computable/symbolic learning objectives"
                if not profile.objective_keys or not has_computable
                else "No computable evidence available"
                if not profile.has_computable_evidence
                else "Science computation capability not ready"
            ),
        ))
    else:
        comp_evidence = profile.computable_evidence_keys or profile.evidence_keys[:3]
        results.append(PracticeSuitability(
            item_type=ItemType.SCIENTIFIC,
            status=SuitabilityStatus.SUPPORTED,
            objective_key=profile.objective_keys[0],
            evidence_keys=comp_evidence,
            reason="Lesson has computable objectives with supporting evidence",
        ))

    return results


def validate_item_type_mode(
    mode: ItemTypeMode,
    suitability: list[PracticeSuitability],
) -> str | None:
    """
    Validate that the requested item type mode can be satisfied.

    Per Spec 004 §6.2:
    - general_only: always succeeds
    - auto: always succeeds (unsupported types are silently skipped)
    - require_coding: fails if coding unsupported
    - require_science: fails if science unsupported

    Returns an error code if the mode cannot be satisfied, None if OK.
    """
    if mode == ItemTypeMode.GENERAL_ONLY:
        return None  # Always OK

    if mode == ItemTypeMode.AUTO:
        return None  # Always OK, unsupported types are skipped

    if mode == ItemTypeMode.REQUIRE_CODING:
        coding = next(
            (s for s in suitability if s.item_type == ItemType.CODING), None
        )
        if coding is None or coding.status == SuitabilityStatus.UNSUPPORTED:
            return "coding_item_not_supported_by_lesson"
        return None

    if mode == ItemTypeMode.REQUIRE_SCIENCE:
        science = next(
            (s for s in suitability if s.item_type == ItemType.SCIENTIFIC), None
        )
        if science is None or science.status == SuitabilityStatus.UNSUPPORTED:
            return "science_item_not_supported_by_lesson"
        return None

    return None  # Unknown mode, let it through (will be caught by schema validation)
