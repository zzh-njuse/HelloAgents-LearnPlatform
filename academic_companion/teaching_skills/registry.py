"""Deterministic loader for the immutable, versioned teaching-skill catalog.

The catalog is a static, allow-listed set of versioned skill directories under
``academic_companion/teaching_skills/<skill-id>/v<version>/SKILL.md``. The product
resolves the single current published skill from the allowlist and snapshots its
id/version/content-hash onto each new Tutor turn. There is no runtime editing, no
client-supplied skill selection and no generic SkillTool for the model.

Security / integrity rules (Spec 003 §5, §10; ADR 005 §3.2):

* only allow-listed (id, version) pairs resolve — unknown ids, unknown versions,
  client prompts and arbitrary paths are rejected;
* skill id and version are validated against strict character classes before they
  are ever used to build a filesystem path, rejecting path traversal outright;
* a resolved skill file's normalized SHA-256 is recomputed on every load; a turn
  snapshot whose hash no longer matches the deployed file fails closed with
  ``teaching_skill_unavailable`` rather than silently upgrading.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SKILLS_ROOT = Path(__file__).resolve().parent

#: The product allowlist. Each entry pins one published (id, version) and its
#: stable UI display name. Adding v2 means a new directory AND a new entry here;
#: v1 is retained so historical turns can still show and retry their version.
ALLOWLIST: tuple[dict[str, str], ...] = (
    {"id": "evidence-guided-diagnostic-scaffold", "version": "2", "display_name": "诊断式支架"},
    {"id": "evidence-guided-diagnostic-scaffold", "version": "1", "display_name": "诊断式支架"},
)

_SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SKILL_VERSION_RE = re.compile(r"^[0-9]+$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class SkillUnavailable(Exception):
    """Raised when a skill cannot be resolved, verified or loaded.

    The product maps this to the stable ``teaching_skill_unavailable`` error code;
    it never falls back to the legacy baseline Tutor (Spec 003 §5.7, §12).
    """


@dataclass(frozen=True)
class TeachingSkill:
    """A resolved, hash-verified teaching skill ready to drive a turn."""

    skill_id: str
    version: str
    display_name: str
    description: str
    body: str
    content_hash: str


def _normalize_body(text: str) -> str:
    """Normalize skill text for a stable cross-platform SHA-256.

    Strips a leading UTF-8 BOM, normalizes CRLF/CR to LF, removes per-line
    trailing whitespace and collapses leading/trailing blank lines. The result is
    independent of the OS that last edited the file, so a snapshot hash stays
    valid across Windows/Linux checkouts.
    """
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip("\n") + "\n"


def compute_content_hash(raw_text: str) -> str:
    """SHA-256 over the normalized full SKILL.md text (UTF-8 encoded)."""
    return hashlib.sha256(_normalize_body(raw_text).encode("utf-8")).hexdigest()


def _allowed_entry(skill_id: str, version: str) -> dict[str, str]:
    for entry in ALLOWLIST:
        if entry["id"] == skill_id and entry["version"] == version:
            return entry
    raise SkillUnavailable("skill_not_in_allowlist")


def _resolve_path(skill_id: str, version: str) -> Path:
    """Resolve the SKILL.md path for an allow-listed (id, version).

    The strict regexes forbid ``/``, ``\\``, leading dots and any character that
    could escape the skills root, so ``skill_id``/``version`` cannot carry a path
    traversal. The resolved path is additionally confirmed to remain under
    ``SKILLS_ROOT`` as defense in depth.
    """
    if not _SKILL_ID_RE.match(skill_id):
        raise SkillUnavailable("invalid_skill_identifier")
    if not _SKILL_VERSION_RE.match(version):
        raise SkillUnavailable("invalid_skill_identifier")
    candidate = SKILLS_ROOT / skill_id / f"v{version}" / "SKILL.md"
    resolved = candidate.resolve()
    root = SKILLS_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:  # pragma: no cover - regex already prevents this
        raise SkillUnavailable("invalid_skill_identifier") from exc
    if os.path.commonpath([str(root), str(resolved)]) != str(root):  # pragma: no cover
        raise SkillUnavailable("invalid_skill_identifier")
    if not resolved.is_file():
        raise SkillUnavailable("skill_not_found")
    return resolved


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        raise SkillUnavailable("invalid_skill_format")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillUnavailable("invalid_skill_format") from exc
    if not isinstance(metadata, dict):
        raise SkillUnavailable("invalid_skill_format")
    return metadata, match.group(2)


def load_skill(skill_id: str, version: str) -> TeachingSkill:
    """Load and hash-verify an allow-listed skill version.

    Raises :class:`SkillUnavailable` for unknown ids/versions, path-traversal
    attempts, missing files, mismatched frontmatter or unparsable files. The
    caller never receives a partial or unverified skill.
    """
    entry = _allowed_entry(skill_id, version)
    path = _resolve_path(skill_id, version)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillUnavailable("skill_not_found") from exc
    metadata, body = _parse_frontmatter(raw_text)
    if metadata.get("id") != skill_id:
        raise SkillUnavailable("skill_metadata_mismatch")
    if str(metadata.get("version")) != version:
        raise SkillUnavailable("skill_metadata_mismatch")
    if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
        raise SkillUnavailable("skill_metadata_mismatch")
    return TeachingSkill(
        skill_id=skill_id,
        version=version,
        display_name=entry["display_name"],
        description=metadata["description"].strip(),
        body=_normalize_body(body),
        content_hash=compute_content_hash(raw_text),
    )


def current_published() -> tuple[str, str]:
    """Return the (id, version) of the single current published skill."""
    if not ALLOWLIST:
        raise SkillUnavailable("no_published_skill")
    head = ALLOWLIST[0]
    return head["id"], head["version"]


def display_name_for(skill_id: str, version: str) -> str | None:
    """Return the allowlist display name for (id, version), or ``None``.

    Read-only and filesystem-free: used to project a historical turn's snapshot
    even after the skill file or a future allowlist entry has changed, so an old
    turn can still render its actual version without re-loading the body.
    """
    for entry in ALLOWLIST:
        if entry["id"] == skill_id and entry["version"] == version:
            return entry["display_name"]
    return None
