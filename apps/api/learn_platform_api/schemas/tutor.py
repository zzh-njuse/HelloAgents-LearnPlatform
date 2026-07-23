from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TutorSessionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    course_version_id: str
    external_processing_ack: bool


class TutorTurnCreate(BaseModel):
    # The client may not choose a teaching mode, skill id/version/hash, skill
    # path or prompt. Forged fields fail with a stable 422 rather than being
    # silently ignored (corr 3.8).
    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, max_length=8000)
    scope: str = Field(pattern="^(course|lesson)$")
    section_id: str | None = None
    lesson_id: str | None = None
    lesson_version_id: str | None = None
    # Slice 4: per-Turn science tool authorization (Spec 004 §6.1, ADR 006 §2.7).
    # Default false; enters idempotency hash. Client cannot specify server,
    # Tool, or budget — only a boolean toggle.
    science_tool_authorized: bool = False
    # Slice 4 packet 002: per-Turn code tool authorization (Spec 004 §8.1).
    # Default false; enters idempotency hash. Independent from science auth.
    code_tool_authorized: bool = False
    # Slice 4: optional code run safe summary for this Turn (Spec 004 §5.1, §9).
    # Must be a terminal, non-deleted CodeLabRun in the same workspace.
    # At most one per Turn; consumed on send, not inherited by next Turn.
    code_run_id: str | None = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be blank")
        return value

    @field_validator("section_id", "lesson_id", "lesson_version_id", "code_run_id", mode="before")
    @classmethod
    def validate_identifier(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("identifiers cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_scope(self):
        values = (self.section_id, self.lesson_id, self.lesson_version_id)
        present = tuple(value is not None for value in values)
        if self.scope == "lesson" and not all(present):
            raise ValueError("lesson scope requires section, lesson, and lesson version")
        if self.scope == "course" and any(present):
            raise ValueError("course scope cannot include lesson identifiers")
        return self


class TutorAnswerBlock(BaseModel):
    block_key: str
    type: Literal[
        "explanation", "example", "check_question", "self_check", "limitation", "memory_summary",
        "direct_answer", "learning_diagnosis", "next_action",
        "science_observation", "code_observation",
    ]
    text: str
    citation_ids: list[str]
    # Only ``learning_diagnosis`` exposes a restricted certainty; every other
    # block carries null. The internal target_ref is never persisted or exposed
    # (corr 3.2/3.6).
    certainty: Literal["confirmed", "provisional", "insufficient", "resolved"] | None = None

    @model_validator(mode="after")
    def validate_certainty(self):
        if self.type != "learning_diagnosis" and self.certainty is not None:
            raise ValueError("certainty is only valid for learning diagnosis blocks")
        return self


class TutorCitationRead(BaseModel):
    citation_id: str
    block_key: str
    document_id: str
    document_version_id: str
    chunk_id: str
    document_name: str
    heading_path: list[str]
    start_offset: int
    end_offset: int
    page_start: int | None = None
    page_end: int | None = None


class TutorTeachingSkillRead(BaseModel):
    """Public projection of the turn's immutable teaching-skill snapshot.

    Only the stable id / display name / version are exposed. The content hash,
    file path and skill prompt body are never published (Spec 003 §10, ADR 005
    §3.3). Historical turns return ``teaching_skill: null``.
    """

    id: str
    display_name: str
    version: str


class TutorTurnRead(BaseModel):
    id: str
    session_id: str
    ordinal: int
    attempt_number: int
    status: str
    question: str
    scope: str
    section_id: str | None
    lesson_id: str | None
    lesson_version_id: str | None
    answer_blocks: list[TutorAnswerBlock] | None
    citations: list[TutorCitationRead] = Field(default_factory=list)
    error_code: str | None
    error_message: str | None
    created_at: str
    completed_at: str | None
    memory_count: int = 0
    completion_count: int = 0
    teaching_skill: TutorTeachingSkillRead | None = None
    # Slice 4: science tool usage summary (Spec 004 §6.1, ADR 006 §2.7)
    science_tool_used: bool = False
    science_tool_call_count: int = 0
    # Slice 4 packet 002: code tool usage summary (Spec 004 §8.1)
    code_tool_used: bool = False
    code_tool_call_count: int = 0


class TutorSessionRead(BaseModel):
    id: str
    workspace_id: str
    course_id: str
    course_version_id: str
    status: str
    provider: str
    model: str
    created_at: str
    turns: list[TutorTurnRead] = Field(default_factory=list)


class TutorSkillCapabilityRead(BaseModel):
    """Server-resolved current teaching skill, readable without a session.

    Lets the Web surface ``教学方法：诊断式支架 v1`` before the first turn. The
    hash and prompt body are intentionally absent.
    """

    teaching_skill: TutorTeachingSkillRead
