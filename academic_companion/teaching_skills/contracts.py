"""Structured contracts for the evidence-guided diagnostic scaffold skill.

These pydantic models constrain the two structured products the skill produces:
the teaching *plan* (first provider call) and the teaching *answer* (second
provider call). They encode Spec 003 §7 (plan) and §8 (answer):

* course-fact blocks must be grounded in the current evidence ledger;
* a learning-state diagnosis never cites course evidence and must carry a
  calibrated certainty;
* teaching moves and intents come from a small finite taxonomy;
* the product never classifies intent by keyword — intent is the model's own
  structured plan output, validated here.

The contracts are deliberately content-agnostic: they never reference any
specific question, fixture phrase or expected answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Intent = Literal["concept_explanation", "learner_diagnosis", "study_planning", "self_check", "other"]
LearningContextUse = Literal["required", "helpful", "irrelevant", "unavailable"]
TeachingMove = Literal["focus", "probe", "explain", "example", "next_action", "check"]
Certainty = Literal["confirmed", "provisional", "insufficient", "resolved"]

#: Block types that state course content and therefore MUST be grounded in the
#: current evidence ledger (Spec 003 §8.1, §8 third validation rule).
FACTUAL_BLOCK_TYPES = frozenset({"direct_answer", "explanation", "example"})
#: Block types that may legitimately carry evidence citations.
CITABLE_BLOCK_TYPES = frozenset({"direct_answer", "explanation", "example"})
#: The taxonomy of teaching moves, derived from MathDial's Focus/Probing/Telling
#: but adapted with an explicit example, next_action and check (Spec 003 §7).
TEACHING_MOVES = ("focus", "probe", "explain", "example", "next_action", "check")


class TeachingPlan(BaseModel):
    """First provider call: how the skill will approach the question."""

    intent: Intent
    queries: list[str] = Field(min_length=1, max_length=3)
    learning_context_use: LearningContextUse
    teaching_moves: list[TeachingMove] = Field(min_length=1, max_length=3)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _normalize_collections(self) -> "TeachingPlan":
        cleaned_queries: list[str] = []
        for query in self.queries:
            if not isinstance(query, str):
                raise ValueError("queries must be strings")
            stripped = query.strip()
            if not stripped or len(stripped) > 300:
                raise ValueError("queries must be 1-300 non-whitespace chars")
            if stripped not in cleaned_queries:
                cleaned_queries.append(stripped)
        if not cleaned_queries:
            raise ValueError("at least one distinct query is required")
        cleaned_moves: list[TeachingMove] = []
        for move in self.teaching_moves:
            if move not in cleaned_moves:
                cleaned_moves.append(move)
        if not cleaned_moves:
            raise ValueError("at least one distinct teaching move is required")
        # Frozen view: reassign normalized values.
        self.queries = cleaned_queries
        self.teaching_moves = cleaned_moves
        return self


class TeachingAnswerBlock(BaseModel):
    """One ordered block of a diagnostic teaching answer.

    Structural rules enforced per block (cross-block and ledger rules are applied
    by the runtime validator in ``tutor_generation``):

    * factual blocks (``direct_answer``/``explanation``/``example``) must cite at
      least one evidence id;
    * ``learning_diagnosis`` must declare a ``certainty`` and must NOT cite course
      evidence (it describes authorized learning state, not course facts);
    * ``certainty`` is only permitted on ``learning_diagnosis``;
    * ``target_ref`` is an INTERNAL, per-turn reference to a projected learning
      target (e.g. ``t1``); it is only permitted on ``learning_diagnosis``, never
      persisted, never exposed in the public API/SSE/Web (stripped before commit);
    * ``limitation`` does not cite.
    """

    block_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    type: Literal["direct_answer", "learning_diagnosis", "explanation", "example", "next_action", "check_question", "limitation"]
    text: str = Field(min_length=1, max_length=8000)
    citation_ids: list[str] = Field(default_factory=list, max_length=10)
    certainty: Certainty | None = None
    target_ref: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,20}$")

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _enforce_block_shape(self) -> "TeachingAnswerBlock":
        cleaned_citations: list[str] = []
        for citation_id in self.citation_ids:
            stripped = citation_id.strip()
            if not stripped:
                raise ValueError("citation ids cannot be blank")
            if stripped not in cleaned_citations:
                cleaned_citations.append(stripped)
        self.citation_ids = cleaned_citations
        if self.type in FACTUAL_BLOCK_TYPES and not self.citation_ids:
            raise ValueError("factual blocks require at least one citation")
        if self.type == "learning_diagnosis":
            if self.certainty is None:
                raise ValueError("learning_diagnosis requires a certainty")
            if self.citation_ids:
                raise ValueError("learning_diagnosis must not cite course evidence")
        else:
            if self.certainty is not None:
                raise ValueError("certainty is only permitted on learning_diagnosis")
            if self.target_ref is not None:
                raise ValueError("target_ref is only permitted on learning_diagnosis")
        if self.type == "limitation" and self.citation_ids:
            raise ValueError("limitation must not cite course evidence")
        if self.type == "next_action" and self.citation_ids:
            # next_action describes a study action, not a course fact.
            raise ValueError("next_action must not cite course evidence")
        return self


class TeachingAnswerArtifact(BaseModel):
    """The full ordered diagnostic answer produced by the second provider call."""

    blocks: list[TeachingAnswerBlock] = Field(min_length=1, max_length=20)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _unique_keys(self) -> "TeachingAnswerArtifact":
        keys = [block.block_key for block in self.blocks]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate block_key")
        return self
