"""Product-owned, versioned teaching skills.

This package owns the immutable, versioned teaching-skill definitions used by the
product Tutor (Platform Stage 4 Slice 3). A teaching skill is a stable, versioned
methodology: it does NOT carry learning facts and never writes Mastery, Weakness,
Review, Memory or Completion state.

The product Tutor deterministically loads the single allow-listed published skill
for every new Slice 3 turn and snapshots its id/version/content-hash on the turn.
It does NOT register a generic SkillTool for the model and never accepts a client-
supplied skill path, id, version, hash or prompt.
"""

from academic_companion.teaching_skills.contracts import (
    TeachingAnswerArtifact,
    TeachingAnswerBlock,
    TeachingPlan,
)
from academic_companion.teaching_skills.registry import (
    SkillUnavailable,
    TeachingSkill,
    compute_content_hash,
    current_published,
    display_name_for,
    load_skill,
)

__all__ = [
    "TeachingAnswerArtifact",
    "TeachingAnswerBlock",
    "TeachingPlan",
    "SkillUnavailable",
    "TeachingSkill",
    "compute_content_hash",
    "current_published",
    "display_name_for",
    "load_skill",
]
