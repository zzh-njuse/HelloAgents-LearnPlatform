"""Safe projection schemas for learning state, review and memory API.

Never exposes projection_score, historical answers, correct answers, rubric,
feedback text, prompts, evidence or provider configuration.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MasteryBandRead(BaseModel):
    target_id: str
    target_title: str
    target_key: str
    band: Literal["insufficient", "needs_review", "developing", "secure"]
    evidence_count: int
    distinct_set_count: int
    deterministic_signal_count: int
    ai_signal_count: int
    last_evidence_at: datetime | None
    weakness_status: str | None
    review_status: str | None
    course_id: str
    lesson_id: str
    source_degraded: bool = False


class LearningStateRead(BaseModel):
    workspace_id: str
    summary: dict[str, int]
    targets: list[MasteryBandRead]


class TargetDetailRead(BaseModel):
    target_id: str
    target_title: str
    band: str
    evidence_count: int
    deterministic_signal_count: int
    ai_signal_count: int
    last_evidence_at: datetime | None
    weakness_status: str | None
    review_status: str | None


class ReviewItemRead(BaseModel):
    id: str
    target_id: str
    target_key: str
    target_title: str
    weakness_status: str
    status: Literal["due", "reviewing", "awaiting_validation", "snoozed", "dismissed", "resolved"]
    due_at: datetime | None
    reopen_count: int
    reason_snapshot: dict[str, object]
    course_id: str
    lesson_id: str
    lesson_title: str
    source_attempt_id: str | None
    source_set_id: str | None
    source_item_ordinal: int | None
    source_is_ai: bool | None
    source_occurred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewActionCreate(BaseModel):
    action: Literal["reviewing", "reviewed", "snooze", "dismiss"]
    snooze_days: int | None = Field(default=None, ge=1, le=30)


class LearningJobRead(BaseModel):
    id: str
    workspace_id: str
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class LearningMemoryRead(BaseModel):
    id: str
    target_title: str
    target_key: str
    kind: str
    status: Literal["active", "needs_review", "paused", "archived"]
    display_text: str
    confirmed_at: datetime | None
    last_supported_at: datetime | None
    source_count: int
    course_id: str
    lesson_id: str
    lesson_title: str
    sources: list[dict[str, object]] = Field(default_factory=list)


class LearningMemoryPatch(BaseModel):
    display_text: str | None = Field(default=None, max_length=2000)
    action: Literal["edit", "pause", "reconfirm", "archive"] | None = None


class LearningMemoryPolicyRead(BaseModel):
    tutor_use_enabled: bool
    policy_revision: int
    updated_at: datetime


class LearningMemoryPolicyPatch(BaseModel):
    tutor_use_enabled: bool
