from pydantic import BaseModel, Field, model_validator


class TutorSessionCreate(BaseModel):
    course_version_id: str
    external_processing_ack: bool


class TutorTurnCreate(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    scope: str = Field(pattern="^(course|lesson)$")
    section_id: str | None = None
    lesson_id: str | None = None
    lesson_version_id: str | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        values = (self.section_id, self.lesson_id, self.lesson_version_id)
        present = tuple(value is not None and bool(value.strip()) for value in values)
        if self.scope == "lesson" and not all(present):
            raise ValueError("lesson scope requires section, lesson, and lesson version")
        if self.scope == "course" and any(present):
            raise ValueError("course scope cannot include lesson identifiers")
        return self


class TutorAnswerBlock(BaseModel):
    block_key: str
    type: str
    text: str
    citation_ids: list[str]


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
