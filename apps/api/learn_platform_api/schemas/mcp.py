"""Schemas for Slice 4 MCP capabilities — code lab and science tools."""

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# MCP Capability / Policy
# ---------------------------------------------------------------------------

class McpCapabilityRead(BaseModel):
    """Public projection of MCP capability readiness."""
    capability: str
    status: str  # ready | unavailable | degraded
    detail: str


class McpPolicyRead(BaseModel):
    """Public projection of workspace MCP policy."""
    workspace_id: str
    code_execution_enabled: bool
    revision: int


class McpPolicyPatch(BaseModel):
    """Patchable fields for workspace MCP policy — extra forbidden."""
    model_config = {"extra": "forbid"}

    code_execution_enabled: bool


# ---------------------------------------------------------------------------
# Code Lab Run
# ---------------------------------------------------------------------------

class CodeRunCreate(BaseModel):
    """Create a code lab run — extra forbidden per Spec 004 §5.2.

    The client may NOT specify endpoint, Tool, runtime, timeout,
    resource limits or snapshot fields.
    """
    model_config = {"extra": "forbid"}

    language: str = Field(pattern="^(python|java|cpp)$")
    source_code: str = Field(min_length=1, max_length=20_000)
    stdin: str = Field(default="", max_length=8_000)
    # Optional navigation grouping
    course_id: str | None = None
    course_version_id: str | None = None
    lesson_id: str | None = None
    lesson_version_id: str | None = None


class CodeRunRead(BaseModel):
    """Public projection of a code lab run.

    Private I/O (source_code, stdin, stdout, stderr, compile_output)
    is only included when the client explicitly requests it and the
    run is in a terminal state.
    """
    id: str
    workspace_id: str
    language: str
    status: str
    course_id: str | None = None
    lesson_id: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    runtime: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    created_at: str
    completed_at: str | None = None
    deleted_at: str | None = None


class CodeRunDetailRead(CodeRunRead):
    """Full detail including private I/O — only for terminal runs."""
    source_code: str = ""
    stdin: str = ""
    compile_output: str = ""
    stdout: str = ""
    stderr: str = ""


class CodeRunSafeSummary(BaseModel):
    """Safe summary for Tutor consumption — no private I/O.

    Per ADR 006 §2.8: safe summary only retains capability, status,
    time, size, duration, version and "deleted object" marker.
    """
    id: str
    language: str
    status: str
    exit_code: int | None = None
    duration_ms: int | None = None
    runtime: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False


# ---------------------------------------------------------------------------
# Tutor Turn Science Tool Authorization
# ---------------------------------------------------------------------------

class ScienceToolAuthorizationRead(BaseModel):
    """Public projection of per-turn science tool authorization."""
    capability_id: str
    max_calls: int
    used_calls: int
    authorized: bool
