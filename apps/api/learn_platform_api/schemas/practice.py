from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PracticeType = Literal["single_choice", "short_answer", "coding", "scientific"]
PracticeDifficulty = Literal["easy", "standard", "hard"]
PracticeLanguage = Literal["zh-CN", "en"]
ItemTypeMode = Literal["auto", "general_only", "require_coding", "require_science"]
CodeLanguage = Literal["python", "java", "cpp"]


class PracticeSetCreate(BaseModel):
    item_count: int = Field(default=5, ge=1, le=10)
    difficulty: PracticeDifficulty = "standard"
    output_language: PracticeLanguage | None = None
    external_processing_ack: bool
    # Slice 4 packet 002: practice type mode and language selection (Spec 004 §7)
    item_type_mode: ItemTypeMode = "auto"
    code_languages: list[CodeLanguage] | None = None
    code_tool_authorized: bool = False
    science_tool_authorized: bool = False

    @model_validator(mode="after")
    def required_tool_authorization(self) -> "PracticeSetCreate":
        if self.item_type_mode == "require_coding":
            if not self.code_tool_authorized:
                raise ValueError("required coding items need code-tool authorization")
            if not self.code_languages:
                raise ValueError("required coding items need at least one language")
        if self.item_type_mode == "require_science" and not self.science_tool_authorized:
            raise ValueError("required scientific items need science-tool authorization")
        return self


class PracticeJobRead(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    job_type: Literal["generate_set", "grade_attempt"]
    practice_set_id: str | None
    practice_attempt_id: str | None
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    science_verification: "ScienceVerificationRead | None" = None


class ScienceVerificationRead(BaseModel):
    used: bool
    status: Literal["verified", "failed", "not_used"]
    tool: Literal["Wolfram"] | None = None
    purpose: Literal["reference_answer", "learner_final_result"]
    checked_at: datetime | None = None


class PracticeOptionRead(BaseModel):
    # Public option projection. Deliberately omits is_correct and rationale.
    option_key: str
    text: str


class PracticeCitationRead(BaseModel):
    citation_key: str
    document_name: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    available: bool


class PracticeItemRead(BaseModel):
    # Pre-submission projection. Omits answer_spec, rubric and reference_answer.
    id: str
    ordinal: int
    item_type: PracticeType
    stem: str
    options: list[PracticeOptionRead] | None
    citations: list[PracticeCitationRead]
    # Slice 4 packet 002: public interaction spec for coding items (no hidden tests)
    interaction_spec: dict | None = None


class PracticeSetRead(BaseModel):
    id: str
    workspace_id: str
    course_id: str
    lesson_id: str
    lesson_version_id: str
    output_language: PracticeLanguage
    difficulty: PracticeDifficulty
    item_count: int
    lifecycle_status: str
    source_degraded: bool
    created_at: datetime
    items: list[PracticeItemRead]


class PracticeSetListItem(BaseModel):
    id: str
    lesson_version_id: str
    output_language: PracticeLanguage
    difficulty: PracticeDifficulty
    item_count: int
    lifecycle_status: str
    source_degraded: bool
    created_at: datetime
    latest_job: PracticeJobRead | None = None


class PracticeAttemptCreate(BaseModel):
    external_processing_ack: bool
    option_key: str | None = Field(default=None, min_length=1, max_length=40)
    text: str | None = Field(default=None, min_length=1, max_length=8000)
    # Slice 4 packet 002: source code for coding attempts (Spec 004 §7)
    source_code: str | None = Field(default=None, min_length=1, max_length=20000)
    science_tool_authorized: bool = False

    @model_validator(mode="after")
    def exactly_one_answer(self) -> "PracticeAttemptCreate":
        provided = sum(1 for v in [self.option_key, self.text, self.source_code] if v is not None)
        if provided != 1:
            raise ValueError("provide exactly one of option_key, text, or source_code")
        if self.option_key is not None and not self.option_key.strip():
            raise ValueError("option_key must not be blank")
        if self.text is not None and not self.text.strip():
            raise ValueError("text must not be blank")
        if self.source_code is not None and not self.source_code.strip():
            raise ValueError("source_code must not be blank")
        return self


class PracticeFeedbackBlockRead(BaseModel):
    block_key: str
    type: Literal["explanation", "improvement", "reference", "limitation"]
    text: str
    citation_ids: list[str]
    option_key: str | None = None


class PracticeCriterionResultRead(BaseModel):
    criterion_key: str
    met: Literal["full", "partial", "none"]
    note: str


class PracticeFeedbackRead(BaseModel):
    verdict: Literal["correct", "partially_correct", "incorrect", "ungradable"]
    score: int | None
    is_ai_graded: bool
    criterion_results: list[PracticeCriterionResultRead]
    feedback_blocks: list[PracticeFeedbackBlockRead]
    citations: list[PracticeCitationRead]
    # Slice 4 packet 002: coding execution summary (Spec 004 §7.3)
    coding_tests_passed: int | None = None
    coding_tests_total: int | None = None
    coding_error_categories: list[str] | None = None
    coding_public_cases: list[dict] | None = None
    science_verification: ScienceVerificationRead | None = None


class PracticeAttemptRead(BaseModel):
    id: str
    practice_item_id: str
    ordinal: int
    item_type: PracticeType
    status: str
    option_key: str | None
    text: str | None
    # Slice 4 packet 002: source code for coding attempts
    source_code: str | None = None
    practice_job_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    feedback: PracticeFeedbackRead | None
