from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=4000)
    audience: str | None = Field(default=None, max_length=500)
    document_ids: list[str] = Field(min_length=1, max_length=20)
    external_processing_ack: bool


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    title: str
    goal: str
    audience: str | None
    lifecycle_status: str
    current_active_version_id: str | None
    created_at: datetime
    updated_at: datetime
    source_degraded: bool = False
    source_count: int = 0
    published_lesson_count: int = 0
    pending_lesson_count: int = 0
    latest_job: "CourseGenerationJobRead | None" = None


class CourseGenerationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    course_id: str
    course_version_id: str | None
    lesson_id: str | None
    job_type: str
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CourseCreateRead(BaseModel):
    course: CourseRead
    job: CourseGenerationJobRead
    source_document_version_ids: list[str]


class LessonGenerationCreate(BaseModel):
    external_processing_ack: bool


class OutlineGenerationCreate(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=20)
    external_processing_ack: bool


class PublishLessonVersion(BaseModel):
    expected_current_published_version_id: str | None


class ActivateCourseVersion(BaseModel):
    expected_current_active_version_id: str | None


CourseRead.model_rebuild()
