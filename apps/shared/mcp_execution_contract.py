"""Canonical MCP execution contract — single source of truth.

Per correction 004 §2: this is the ONLY module that defines the Pydantic
input/output models, their canonical schema hashes, and the fixed Tool
identity. Both the API/worker image and the execution MCP server image
import from here. No fallback, no duplication, no hand-written schemas.

If either image cannot import this module, it must fail — never silently
fall back to a local copy that may drift.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Fixed constants — per Spec 004 §5.2, ADR 006 §2.3/2.5
# ---------------------------------------------------------------------------

ALLOWED_LANGUAGES = ("python", "java", "cpp")
SOURCE_CODE_MAX_CHARS = 20_000
STDIN_MAX_CHARS = 8_000
OUTPUT_MAX_BYTES = 32 * 1024  # 32 KiB per field
WALL_TIME_SECONDS = 3.0
COMPILE_TIME_SECONDS = 10.0

# MCP protocol version fixed per ADR 006 §2.3
MCP_PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "learn-platform-code-execution"
SERVER_VERSION = "1.0.0"

# Tool identity
TOOL_NAME = "run_code"
TOOL_DESCRIPTION = "Execute Python, Java, or C++ code in an isolated sandbox"


# ---------------------------------------------------------------------------
# Canonical Pydantic models — the ONLY definition
# ---------------------------------------------------------------------------

class RunCodeInput(BaseModel):
    """Fixed input contract — extra fields forbidden (Spec 004 §5.2)."""

    model_config = {"extra": "forbid"}

    request_id: str = Field(min_length=1, max_length=64)
    language: str = Field(pattern="^(python|java|cpp)$")
    source_code: str = Field(min_length=1, max_length=SOURCE_CODE_MAX_CHARS)
    stdin: str = Field(default="", max_length=STDIN_MAX_CHARS)


class ExecutionStatus(StrEnum):
    completed = "completed"
    compile_error = "compile_error"
    runtime_error = "runtime_error"
    timed_out = "timed_out"
    output_limited = "output_limited"


class RunCodeOutput(BaseModel):
    """Fixed output contract — extra fields forbidden (Spec 004 §5.2)."""

    model_config = {"extra": "forbid"}

    status: ExecutionStatus
    exit_code: int
    compile_output: str = Field(max_length=OUTPUT_MAX_BYTES)
    stdout: str = Field(max_length=OUTPUT_MAX_BYTES)
    stderr: str = Field(max_length=OUTPUT_MAX_BYTES)
    duration_ms: int = Field(ge=0)
    runtime: str = Field(max_length=100)
    stdout_truncated: bool
    stderr_truncated: bool


# ---------------------------------------------------------------------------
# Canonical schema hashes — computed once at import time
# ---------------------------------------------------------------------------

def _compute_canonical_hash(schema: dict) -> str:
    """Compute a stable hash of a JSON schema dict.

    Uses json.dumps(schema, sort_keys=True) for deterministic serialization.
    Both images must produce identical hashes for the same schema.
    """
    canonical = json.dumps(schema, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


INPUT_SCHEMA_HASH = _compute_canonical_hash(RunCodeInput.model_json_schema())
OUTPUT_SCHEMA_HASH = _compute_canonical_hash(RunCodeOutput.model_json_schema())


# ---------------------------------------------------------------------------
# Canonical schema dicts — for MCP server Tool registration
# ---------------------------------------------------------------------------

INPUT_SCHEMA = RunCodeInput.model_json_schema()
OUTPUT_SCHEMA = RunCodeOutput.model_json_schema()


# ---------------------------------------------------------------------------
# Shared canonical hash function (correction 006 §4)
# ---------------------------------------------------------------------------

def compute_canonical_hash(schema: dict) -> str:
    """Compute a stable hash of a JSON schema dict.

    This is the single shared implementation used by the probe,
    the tutor science call, and the code lab execution service.
    Per correction 006 §4: probe and Tutor must reuse this same function,
    no duplicated algorithm.
    """
    return _compute_canonical_hash(schema)
