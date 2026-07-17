from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PracticeType = Literal["single_choice", "short_answer"]
PracticeDifficulty = Literal["easy", "standard", "hard"]
PracticeLanguage = Literal["zh-CN", "en"]


class PracticeSetCreate(BaseModel):
    item_count: int = Field(default=5, ge=1, le=10)
    difficulty: PracticeDifficulty = "standard"
    output_language: PracticeLanguage | None = None
    external_processing_ack: bool


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

    @model_validator(mode="after")
    def exactly_one_answer(self) -> "PracticeAttemptCreate":
        if (self.option_key is not None) == (self.text is not None):
            raise ValueError("provide exactly one of option_key or text")
        if self.option_key is not None and not self.option_key.strip():
            raise ValueError("option_key must not be blank")
        if self.text is not None and not self.text.strip():
            raise ValueError("text must not be blank")
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


class PracticeAttemptRead(BaseModel):
    id: str
    practice_item_id: str
    ordinal: int
    item_type: PracticeType
    status: str
    option_key: str | None
    text: str | None
    practice_job_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    feedback: PracticeFeedbackRead | None
