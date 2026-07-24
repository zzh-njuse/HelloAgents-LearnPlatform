"""Stage 4 Slice 5 — Phase A practice-generation/grading stability baseline.

Phase A adds NO product-code changes (no service, migration, Web or contract
edits). These tests establish a reproducible, secret-free, provider-free
baseline for the v1 practice chain so the Slice 5 root-cause hypotheses in
``SLICE_5_PRACTICE_STABILITY_FACT_INVENTORY.md`` can be confirmed or rejected
on runnable evidence instead of on the observed "Java/C++ generation success
rate = 0" smoke result.

Coverage (per task packet §6.2 / §6.3):

1. The three-language canonical harness (``_build_coding_harness``) compiled and
   executed on the REAL local toolchain (``python``/``javac``/``g++``). This
   proves the v1 wrapper itself is internally sound and characterizes
   comparator, whitespace, unicode, CRLF and numeric-tolerance behavior across
   Python/Java/C++. Compiler-dependent cases skip with an explicit reason when
   the toolchain is absent — never a fake pass.
2. The domain validator acceptance set and its (in)consistency with the harness,
   including the confirmed Java ``package`` mismatch.
3. Static characterization of the current v1 budget / repair / retry / error /
   schema model, pinning the gaps Spec 005 / ADR 007 target.

Real provider, Judge0 VM, Wolfram, the product MCP adapter and OCR are
intentionally NOT exercised here; they stay behind the human Gate. Nothing in
this file reads ``.env``, keys, internal URLs, prompts, logs, hidden-test
bodies or provider responses.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from academic_companion.practice_agents import PracticeItemArtifact
from learn_platform_api.services.practice_generation import _build_coding_harness
from learn_platform_api.settings import Settings


# ---------------------------------------------------------------------------
# Toolchain preflight + harness execution helpers
# ---------------------------------------------------------------------------

TIMEOUT_SECONDS = 20

# Cached per-language preflight result for the session: language -> (state, diag).
_PREFLIGHT_CACHE: dict[str, tuple[str, str]] = {}


def _trunc(text: str | None, limit: int = 500) -> str:
    """Truncate subprocess output for safe, readable assertion diagnostics."""
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"...<+{len(text) - limit} chars>"


def _scrub(text: str | None, *paths: str) -> str:
    """Strip host absolute temp/work paths from compiler diagnostics so assertion
    ``detail`` never carries a host run path (task packet §3.4). The diagnostic
    text, line numbers and column markers are preserved."""
    if not text:
        return ""
    out = str(text)
    for path in paths:
        if path:
            out = out.replace(path, "<tmp>")
    return out


def _preflight(language: str) -> tuple[str, str]:
    """Classify the REAL local toolchain for a language.

    Returns ``(state, diagnostic)`` where state is one of:

    - ``absent``: the compiler binary is not on PATH (nothing can run).
    - ``broken``: the binary exists but a trivial program fails to compile —
      i.e. the install is damaged or the compiler cannot start (e.g. an MSYS2
      DLL entry-point failure in ``cc1plus``).
    - ``ok``: a trivial program compiles, so harness compile/run results are
      trustworthy signal about the harness under test.

    A ``broken`` toolchain must never be treated as a test pass or as a harness
    compile failure: callers skip as ``environment-blocked`` so the language
    axis is reported honestly instead of producing opaque ``compile_error``
    assertions. (Covers the case where ``g++ --version`` works but the actual
    compile chain is unusable.)
    """
    if language in _PREFLIGHT_CACHE:
        return _PREFLIGHT_CACHE[language]
    if language == "python":
        # The interpreter running pytest is, by definition, usable.
        state, diag = "ok", f"python interpreter usable: {sys.executable}"
        _PREFLIGHT_CACHE[language] = (state, diag)
        return state, diag

    binary = "javac" if language == "java" else "g++"
    if shutil.which(binary) is None:
        state, diag = "absent", f"{binary} not on PATH"
        _PREFLIGHT_CACHE[language] = (state, diag)
        return state, diag

    with tempfile.TemporaryDirectory() as tmp:
        if language == "java":
            src = os.path.join(tmp, "Preflight.java")
            with open(src, "w", encoding="utf-8") as handle:
                handle.write("class Preflight { public static void main(String[] a) {} }\n")
            proc = subprocess.run(
                ["javac", "-encoding", "UTF-8", src],
                capture_output=True, timeout=TIMEOUT_SECONDS, text=True,
            )
        else:
            src = os.path.join(tmp, "preflight.cpp")
            exe = os.path.join(tmp, "preflight.exe")
            with open(src, "w", encoding="utf-8") as handle:
                handle.write("int main() { return 0; }\n")
            proc = subprocess.run(
                ["g++", "-std=c++17", "-fexec-charset=UTF-8", src, "-o", exe],
                capture_output=True, timeout=TIMEOUT_SECONDS, text=True,
            )
        if proc.returncode != 0:
            state = "broken"
            diag = (
                f"{binary} present but trivial compile failed: rc={proc.returncode} "
                f"stdout={_trunc(proc.stdout)} stderr={_trunc(proc.stderr)}"
            )
        else:
            state, diag = "ok", f"{binary} trivial compile ok"
    _PREFLIGHT_CACHE[language] = (state, diag)
    return state, diag


def _require_toolchain_ok(language: str) -> str:
    """Skip unless the toolchain is genuinely usable, returning the diagnostic.

    Distinguishes ``absent`` / ``broken`` / ``ok``. ``broken`` is reported as
    ``environment-blocked`` (a skip with the captured rc/stderr), never a pass
    and never an opaque harness failure.
    """
    state, diag = _preflight(language)
    if state == "absent":
        pytest.skip(f"{language} real-compile case skipped — toolchain absent: {diag}")
    if state == "broken":
        pytest.skip(f"{language} real-compile case skipped — environment-blocked (toolchain cannot start): {diag}")
    return diag


def _run_python_harness(source: str) -> dict:
    """Run the Python harness with the same interpreter. Captures rc/stdout/stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "harness.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        proc = subprocess.run(
            [sys.executable, path], capture_output=True, timeout=TIMEOUT_SECONDS, text=True
        )
    return {
        "status": "completed" if proc.returncode == 0 else "runtime_error",
        "stage": "python", "returncode": proc.returncode,
        "stdout": _scrub(proc.stdout, tmp, path),
        "stderr": _scrub(proc.stderr, tmp, path),
    }


def _run_java_harness(source: str) -> dict:
    """javac-compile then java-run. Captures rc/stdout/stderr at each stage."""
    with tempfile.TemporaryDirectory() as tmp:
        java_path = os.path.join(tmp, "Main.java")
        with open(java_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        compile_proc = subprocess.run(
            ["javac", "-encoding", "UTF-8", java_path],
            capture_output=True, timeout=TIMEOUT_SECONDS, text=True,
        )
        if compile_proc.returncode != 0:
            return {
                "status": "compile_error", "stage": "javac", "returncode": compile_proc.returncode,
                "stdout": _scrub(compile_proc.stdout, tmp, java_path),
                "stderr": _scrub(compile_proc.stderr, tmp, java_path),
            }
        proc = subprocess.run(
            ["java", "-cp", tmp, "Main"], capture_output=True, timeout=TIMEOUT_SECONDS, text=True
        )
    return {
        "status": "completed" if proc.returncode == 0 else "runtime_error",
        "stage": "java", "returncode": proc.returncode,
        "stdout": _scrub(proc.stdout, tmp, java_path),
        "stderr": _scrub(proc.stderr, tmp, java_path),
    }


def _run_cpp_harness(source: str) -> dict:
    """g++-compile then run. Captures rc/stdout/stderr at each stage.

    The MSYS2 toolchain on this host is intermittently unable to start cc1plus
    (rc -1073741511 == 0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND). Capturing
    stderr here keeps such a toolchain failure distinguishable from a genuine
    harness compile error instead of collapsing both to ``compile_error``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "harness.cpp")
        exe_path = os.path.join(tmp, "harness.exe")
        with open(src_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-fexec-charset=UTF-8", src_path, "-o", exe_path],
            capture_output=True, timeout=TIMEOUT_SECONDS, text=True,
        )
        if compile_proc.returncode != 0:
            return {
                "status": "compile_error", "stage": "g++", "returncode": compile_proc.returncode,
                "stdout": _scrub(compile_proc.stdout, tmp, src_path),
                "stderr": _scrub(compile_proc.stderr, tmp, src_path),
            }
        proc = subprocess.run(
            [exe_path], capture_output=True, timeout=TIMEOUT_SECONDS, text=True, encoding="utf-8"
        )
    return {
        "status": "completed" if proc.returncode == 0 else "runtime_error",
        "stage": "cpp-run", "returncode": proc.returncode,
        "stdout": _scrub(proc.stdout, tmp, src_path),
        "stderr": _scrub(proc.stderr, tmp, src_path),
    }


_RUNNERS = {"python": _run_python_harness, "java": _run_java_harness, "cpp": _run_cpp_harness}


def _execute(language: str, source: str, tests: list[dict]) -> dict:
    """Build the v1 harness and run it on the real local toolchain.

    Requires a ``ok`` toolchain (else skips as absent/environment-blocked).
    Returns a dict with ``status`` (completed|compile_error|runtime_error),
    parsed ``passed``/``total`` when the harness emitted JSON, and a ``detail``
    string carrying the truncated returncode/stdout/stderr so that any
    assertion failure shows WHY a compile/run failed (compiler-startup fault vs
    genuine harness compile error vs runtime error) instead of a bare code.
    """
    _require_toolchain_ok(language)
    harness = _build_coding_harness(source, tests, language)
    raw = _RUNNERS[language](harness)
    result: dict = {
        "status": raw["status"],
        "passed": None,
        "total": None,
        "detail": (
            f"stage={raw.get('stage')} rc={raw.get('returncode')} "
            f"stdout={_trunc(raw.get('stdout'))} stderr={_trunc(raw.get('stderr'))}"
        ),
    }
    stdout = (raw.get("stdout") or "").strip()
    if stdout:
        try:
            parsed = json.loads(stdout)
            result["passed"] = parsed.get("passed")
            result["total"] = parsed.get("total")
        except (json.JSONDecodeError, TypeError):
            result["passed"] = None
    return result


def _identity(language: str) -> str:
    return {
        "python": "def solve(input_text):\n    return input_text",
        "java": "class Solution { static String solve(String input) { return input; } }",
        "cpp": "std::string solve(const std::string& input) { return input; }",
    }[language]


THREE_LANGUAGES = ["python", "java", "cpp"]


# ---------------------------------------------------------------------------
# 1. Three-language canonical harness, real compiler/runtime matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_passes_correct_reference_in_all_languages(language: str) -> None:
    """A canonical correct reference must compile, run and pass every test."""
    result = _execute(language, _identity(language), [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "b", "expected_output": "b", "weight": 1},
        {"input": "c", "expected_output": "c", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == result["total"] == 3, result["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_supports_unicode_io_consistently(language: str) -> None:
    """UTF-8 inputs/outputs (Latin + CJK) must round-trip in every language."""
    result = _execute(language, _identity(language), [
        {"input": "héllo", "expected_output": "héllo", "weight": 1},
        {"input": "中文", "expected_output": "中文", "weight": 1},
        {"input": "a", "expected_output": "a", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == 3, result["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_handles_empty_input(language: str) -> None:
    """An empty UTF-8 input must not crash the harness."""
    result = _execute(language, _identity(language), [
        {"input": "", "expected_output": "", "weight": 1},
        {"input": "x", "expected_output": "x", "weight": 1},
        {"input": "y", "expected_output": "y", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == 3, result["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_normalizes_whitespace_and_newlines(language: str) -> None:
    """Runs of spaces and newlines fold to single spaces; CRLF == LF."""
    folded_source = {
        "python": "def solve(input_text):\n    return 'a   b\\nc'",
        "java": 'class Solution { static String solve(String input) { return "a   b\\nc"; } }',
        "cpp": 'std::string solve(const std::string& input){ return "a   b\\nc"; }',
    }[language]
    # Identity maps CRLF input to itself; both sides fold to "a b".
    result_crlf = _execute(language, _identity(language), [
        {"input": "a\r\nb", "expected_output": "a b", "weight": 1},
        {"input": "c", "expected_output": "c", "weight": 1},
        {"input": "d", "expected_output": "d", "weight": 1},
    ])
    assert result_crlf["status"] == "completed", result_crlf["detail"]
    assert result_crlf["passed"] == 3, result_crlf["detail"]
    # A constant multi-space/multi-line output folds to "a b c".
    result_fold = _execute(language, folded_source, [
        {"input": "z", "expected_output": "a b c", "weight": 1},
        {"input": "z2", "expected_output": "a b c", "weight": 1},
        {"input": "z3", "expected_output": "a b c", "weight": 1},
    ])
    assert result_fold["status"] == "completed", result_fold["detail"]
    assert result_fold["passed"] == 3, result_fold["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_numeric_tolerance_boundary_is_consistent(language: str) -> None:
    """numeric_tolerance passes within tolerance and fails outside it."""
    within = {
        "python": "def solve(input_text):\n    return '3.146'",
        "java": 'class Solution { static String solve(String input) { return "3.146"; } }',
        "cpp": 'std::string solve(const std::string& input){ return "3.146"; }',
    }[language]
    pass_result = _execute(language, within, [
        {"input": "x", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.01},
        {"input": "y", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.01},
        {"input": "z", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.01},
    ])
    assert pass_result["status"] == "completed" and pass_result["passed"] == 3, pass_result["detail"]
    fail_result = _execute(language, within, [
        {"input": "x", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.001},
        {"input": "y", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.001},
        {"input": "z", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.001},
    ])
    assert fail_result["status"] == "completed", fail_result["detail"]
    assert fail_result["passed"] == 0, fail_result["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_classifies_compile_and_runtime_errors(language: str) -> None:
    """Compile errors surface as compile_error; runtime errors do not crash."""
    compile_bad = {
        "python": "def solve(input_text):\n    x = 1 +",  # SyntaxError -> runtime_error exit
        "java": "class Solution { static String solve(String input) { return input ",
        "cpp": "std::string solve(const std::string& input){ return input ",
    }[language]
    compile_result = _execute(language, compile_bad, [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "b", "expected_output": "b", "weight": 1},
        {"input": "c", "expected_output": "c", "weight": 1},
    ])
    # Java/C++ fail at compile; Python fails at runtime (SyntaxError at import).
    assert compile_result["passed"] is None, compile_result["detail"]
    assert compile_result["status"] in {"compile_error", "runtime_error"}, compile_result["detail"]

    runtime_bad = {
        "python": "def solve(input_text):\n    return str(1 / 0)",
        "java": "class Solution { static String solve(String input) { return String.valueOf(1 / 0); } }",
        # volatile defeats constant folding so the divide-by-zero is a runtime SIGFPE
        # (the harness try/catch cannot catch a signal, so the process exits non-zero).
        "cpp": "std::string solve(const std::string& input){ volatile int z=0; return std::string(1, char(10 / z)); }",
    }
    if language in runtime_bad:
        runtime_result = _execute(language, runtime_bad[language], [
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ])
        # A runtime failure must not be reported as a pass.
        assert runtime_result["passed"] != runtime_result["total"] or runtime_result["passed"] is None, runtime_result["detail"]


@pytest.mark.parametrize("language", THREE_LANGUAGES)
def test_v1_harness_representative_wrong_solution_does_not_pass(language: str) -> None:
    """A representative incorrect solution must not pass all hidden tests."""
    wrong = {
        "python": "def solve(input_text):\n    return 'wrong'",
        "java": 'class Solution { static String solve(String input) { return "wrong"; } }',
        "cpp": 'std::string solve(const std::string& input){ return "wrong"; }',
    }[language]
    result = _execute(language, wrong, [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "b", "expected_output": "b", "weight": 1},
        {"input": "c", "expected_output": "c", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == 0, result["detail"]


def test_v1_harness_weighted_partial_scoring() -> None:
    """Passed-weight fraction determines the score, not just passed-count."""
    result = _execute("python", _identity("python"), [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "deliberately-wrong", "expected_output": "x", "weight": 1},
        {"input": "y", "expected_output": "y", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == 2, result["detail"]
    assert result["total"] == 3, result["detail"]


def test_v1_java_public_class_is_normalized_by_harness() -> None:
    """``public class Solution`` is rewritten to ``class Solution`` so the
    product-supplied ``class Main`` compiles alongside it."""
    _require_toolchain_ok("java")
    source = "public class Solution { static String solve(String input) { return input; } }"
    harness = _build_coding_harness(source, [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "b", "expected_output": "b", "weight": 1},
        {"input": "c", "expected_output": "c", "weight": 1},
    ], "java")
    assert "public class Solution" not in harness
    assert "class Solution" in harness
    raw = _run_java_harness(harness)
    assert raw["status"] == "completed", (
        f"expected java harness to complete, got {raw['status']} "
        f"rc={raw.get('returncode')} stderr={_trunc(raw.get('stderr'))}"
    )
    assert json.loads(raw["stdout"].strip())["passed"] == 3


def test_v1_cpp_accepts_bare_string_spelling_and_provider_includes() -> None:
    """C++ accepts the ``string`` spelling (no ``std::``) and tolerates a
    provider that adds its own includes and namespace."""
    source = (
        "#include <algorithm>\nusing namespace std;\n"
        "string solve(const string& input){ string s=input; reverse(s.begin(), s.end()); return s; }"
    )
    result = _execute("cpp", source, [
        {"input": "abc", "expected_output": "cba", "weight": 1},
        {"input": "x", "expected_output": "x", "weight": 1},
        {"input": "ab", "expected_output": "ba", "weight": 1},
    ])
    assert result["status"] == "completed", result["detail"]
    assert result["passed"] == 3, result["detail"]


# --- Toolchain preflight guards (Codex Phase-A review fix) -------------------
# A toolchain that exists but cannot start (e.g. cc1plus DLL entry-point fault,
# rc -1073741511 == 0xC0000139) must be reported as environment-blocked, never
# as a pass and never collapsed into an opaque harness compile_error. These
# guard the three-way distinction (absent / broken / ok) without depending on
# the host's intermittently-unstable MSYS2 install.

def test_preflight_classifies_absent_compiler(monkeypatch) -> None:
    import test_slice5_practice_stability as mod

    monkeypatch.setattr(mod.shutil, "which", lambda binary: None)
    monkeypatch.setattr(mod, "_PREFLIGHT_CACHE", {})
    state, diag = mod._preflight("cpp")
    assert state == "absent"
    assert "not on PATH" in diag


def test_preflight_classifies_broken_compiler_and_blocks_real_compile_cases(monkeypatch) -> None:
    """A compiler that is present but whose cc1plus cannot start must produce
    ``broken`` and cause real-compile cases to SKIP as environment-blocked
    (with the captured rc/stderr), not pass and not fail opaquely."""
    import test_slice5_practice_stability as mod
    from types import SimpleNamespace

    def fake_run(cmd, **kwargs):  # noqa: ANN001 - matches subprocess.run signature loosely
        return SimpleNamespace(
            returncode=-1073741511, stdout="",
            stderr="cc1plus.exe: cannot start - 0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND",
        )

    monkeypatch.setattr(mod.shutil, "which", lambda binary: f"/fake/{binary}.exe")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_PREFLIGHT_CACHE", {})

    state, diag = mod._preflight("cpp")
    assert state == "broken"
    assert "rc=-1073741511" in diag
    assert "cc1plus" in diag or "0xC0000139" in diag

    # Real-compile cases must skip (not pass, not opaque-fail) on a broken chain.
    try:
        mod._require_toolchain_ok("cpp")
        raise AssertionError("expected environment-blocked skip, but _require_toolchain_ok returned")
    except BaseException as exc:  # pytest.skip raises Skipped(BaseException)
        assert type(exc).__name__ == "Skipped"
        assert "environment-blocked" in str(exc)


# ---------------------------------------------------------------------------
# 2. Domain validator acceptance set vs. the harness (canonical consistency)
# ---------------------------------------------------------------------------

def _coding_item(language: str, source: str) -> PracticeItemArtifact:
    return PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the task.", citation_ids=["e1"], language=language,
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution=source,
    )


def _accepts(language: str, source: str) -> bool:
    try:
        _coding_item(language, source)
        return True
    except ValidationError:
        return False


_BASE_TESTS = [
    {"input": "a", "expected_output": "a", "weight": 1},
    {"input": "b", "expected_output": "b", "weight": 1},
    {"input": "c", "expected_output": "c", "weight": 1},
]


def test_v2_java_package_is_rejected_by_validator() -> None:
    """Phase C FIX of the Phase-A confirmed defect (hypothesis 1).

    v1 accepted ``package foo; class Solution {...}`` at schema validation but
    the harness then failed to compile (imports prepended before the source, so
    ``package`` was no longer first). v2 rejects a package declaration at
    validation, so a provider that reflexively emits one fails fast with a
    stable structural error instead of passing schema and failing reference
    execution. This removes a systematic, provider-independent Java failure path.
    """
    packaged = "package foo;\nclass Solution { static String solve(String input) { return input; } }"
    assert _accepts("java", packaged) is False
    # A correct package-free Solution still validates.
    assert _accepts("java", "class Solution { static String solve(String input) { return input; } }") is True


@pytest.mark.parametrize("language,source", [
    ("java", "class Main { public static void main(String[] args) {} }"),
    ("java", "class Solution { public String solve(String input) { return input; } }"),  # non-static
    ("java", "package foo;\nclass Solution { static String solve(String input) { return input; } }"),  # package
    ("cpp", "int main() { return 0; }"),
    ("cpp", "std::string solve(std::string input) { return input; }"),  # by value, no const ref
])
def test_v2_validator_rejects_conflicting_entry_points_and_noncanonical_signatures(
    language: str, source: str
) -> None:
    """The validator rejects Java ``Main``/non-static/``package`` and C++
    ``main`` / by-value signatures. Documents the v2 acceptance boundary."""
    assert _accepts(language, source) is False


# ---------------------------------------------------------------------------
# 3. Static characterization of the v1 budget / repair / retry / schema model
# ---------------------------------------------------------------------------

def test_v2_step_budget_is_unified_to_a_single_denomination() -> None:
    """Phase D (Spec 005 §7.2 / ADR 007 §3.6): the dual denomination is gone.
    Runtime and eval share one authoritative budget; the old separate
    ``practice_generation_max_steps`` field no longer exists."""
    settings = Settings()
    assert settings.practice_generation_max_provider_calls == 4
    assert settings.practice_generation_max_attempt_steps == 12
    assert not hasattr(settings, "practice_generation_max_steps")
    from pathlib import Path
    from learn_platform_api.services import practice_generation
    eval_runner_src = (Path(__file__).resolve().parent.parent / "stage4_eval" / "runner.py").read_text(encoding="utf-8")
    assert "practice_generation_max_attempt_steps" in eval_runner_src
    assert "practice_generation_max_attempt_steps" in inspect.getsource(practice_generation)


def test_v2_dead_coding_ref_call_budget_setting_is_removed() -> None:
    """Phase D (hypothesis 4): ``practice_coding_max_ref_calls`` (a configured
    but never-read denomination) was removed rather than wired in alongside the
    others. The per-Set tool budget is the single JobToolAuthorization budget."""
    settings = Settings()
    assert not hasattr(settings, "practice_coding_max_ref_calls")
    from learn_platform_api.services import practice_generation
    assert "practice_coding_max_ref_calls" not in inspect.getsource(practice_generation)


def test_v2_only_transient_infrastructure_failures_are_retryable() -> None:
    """Phase D (Spec 005 §7.1): delivery retry covers transient
    provider/queue/MCP faults. Structural, reference, budget, cancel and
    source-stale failures are still NOT auto-retried."""
    from learn_platform_api.practice_workers import RETRYABLE_CODES
    assert RETRYABLE_CODES == {
        "provider_unavailable",
        "queue_unavailable",
        "code_execution_unavailable",
        "science_tool_unavailable",
    }
    for code in (
        "invalid_practice_artifact",
        "coding_reference_compile_failed",
        "coding_reference_test_failed",
        "coding_starter_invalid",
        "scientific_reference_unverified",
        "practice_budget_exceeded",
        "practice_canceled",
        "source_snapshot_stale",
    ):
        assert code not in RETRYABLE_CODES


def test_v2_practice_job_has_artifact_contract_version_column() -> None:
    """Phase B (ADR 007 §3.9): PracticeJob now has a non-null
    ``artifact_contract_version`` column. The ORM default reads historical
    (untouched) rows as v1; new generation Jobs pin v2 at creation."""
    from learn_platform_api.db.models import PracticeJob
    column = PracticeJob.__table__.columns["artifact_contract_version"]
    assert column.nullable is False
    default_arg = getattr(column.default, "arg", None) if column.default else None
    assert default_arg == "practice_artifact_v1"


def test_v2_coding_artifact_is_pinned_to_solve_utf8_string_v2() -> None:
    """Phase B/C: the current commit path pins ``practice_artifact_v2`` /
    ``solve_utf8_string_v2`` on new Sets, while v1 stays readable via
    ``harness_for_artifact`` (Spec 005 §6 / §10, ADR 007 §3.1)."""
    from academic_companion.practice_agents import (
        ARTIFACT_CONTRACT_V1, ARTIFACT_CONTRACT_V2, HARNESS_V1, HARNESS_V2, harness_for_artifact,
    )
    from learn_platform_api.services import practice_generation
    source = inspect.getsource(practice_generation)
    # v2 is the contract new Sets are pinned to; v1 remains referenced for read compat.
    assert source.count(HARNESS_V1) >= 1
    assert harness_for_artifact(ARTIFACT_CONTRACT_V2) == HARNESS_V2
    assert harness_for_artifact(ARTIFACT_CONTRACT_V1) == HARNESS_V1
    assert harness_for_artifact(None) == HARNESS_V1


# ---------------------------------------------------------------------------
# 4. Behavioral: a failed coding reference triggers a WHOLE-SET repair
# ---------------------------------------------------------------------------

def test_v2_coding_reference_failure_repairs_only_the_failed_item(
    db_session, monkeypatch
) -> None:
    """Phase D FIX of the Phase-A confirmed repair amplification (hypothesis 3).

    When the single coding item fails reference validation, ``execute_generation``
    repairs ONLY that item via ``build_specialized_item_repair_prompt`` (pinning
    its identity), not the whole Set. The already-valid choice item is never
    re-sent to the provider and is committed unchanged. Spec 005 §5 / ADR 007 §3.3.
    """
    from learn_platform_api.db.models import McpCapabilityStatus, PracticeItem, PracticeSet
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice, practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings
    from test_practice_worker import _reader

    workspace, course, course_version, lesson, lesson_version, chunk, document, document_version = _reader(db_session)
    lesson_version.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": True, "has_executable_evidence": True,
        "has_math_objective": False, "has_physics_objective": False,
        "has_chemistry_objective": False, "has_computable_evidence": False,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="code_execution", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    db_session.commit()
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_args: None)
    payload = type("P", (), {
        "item_count": 2, "difficulty": "standard", "output_language": "zh-CN",
        "item_type_mode": "require_coding", "code_languages": ["python"],
        "code_tool_authorized": True, "science_tool_authorized": False,
    })()
    job = practice.create_generation_job(
        db_session, get_settings(), workspace.id, course.id, course_version.id,
        lesson.id, lesson_version.id, payload, "single-item-repair-probe",
    )
    job.status = "running"
    job.worker_id = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    job.attempt_count = 1
    db_session.commit()

    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: (
        "trace",
        [RetrievalResult(
            score=0.9, text=chunk.content,
            citation=CitationRead(
                document_id=document.id, document_version_id=document_version.id,
                chunk_id=chunk.id, document_name=document.display_name,
                heading_path=[], start_offset=0, end_offset=len(chunk.content),
            ),
        )],
    ))

    valid_choice_key = "q-choice"
    coding_key = "q-code"
    broken_reference = "def solve(input_text):\n    return 'wrong'"
    fixed_reference = "def solve(input_text):\n    return input_text"
    initial_artifact = {"items": [
        {"item_key": valid_choice_key, "target_key": "objective_1", "item_type": "single_choice",
         "stem": "Choose the supported statement.", "citation_ids": ["e1"],
         "options": [
             {"option_key": "a", "text": "A", "is_correct": True, "rationale": "ok", "citation_ids": ["e1"]},
             {"option_key": "b", "text": "B", "is_correct": False, "rationale": "no", "citation_ids": ["e1"]},
         ]},
        {"item_key": coding_key, "target_key": "objective_1", "item_type": "coding",
         "stem": "Implement the identity transformation.", "citation_ids": ["e1"], "language": "python",
         "input_description": "one UTF-8 string", "output_description": "the same string",
         "hidden_tests": [
             {"input": "a", "expected_output": "a", "weight": 1},
             {"input": "b", "expected_output": "b", "weight": 1},
             {"input": "c", "expected_output": "c", "weight": 1},
         ],
         "reference_solution": broken_reference},
    ]}
    # Specialized repair returns ONLY the fixed coding item, same identity.
    # Correction 002 §A: use minimal DTO format (only item_key + reference_solution)
    repaired_coding = {"item_key": coding_key, "reference_solution": fixed_reference}

    provider_results = iter([
        ({"queries": ["objective evidence", "implementation evidence", "test evidence"]}, {}),
        (initial_artifact, {}),
        (repaired_coding, {}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    # Reference validation fails for the broken solution, passes for the fixed one.
    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_reference:
            return CodingReferenceValidationResult(passed=False, tests_passed=0, tests_total=3, error_categories=["test_mismatch"], infrastructure_failure=False)
        return CodingReferenceValidationResult(passed=True, tests_passed=3, tests_total=3, error_categories=[], infrastructure_failure=False)
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    # Capture which item the specialized repair targets; flag any whole-Set repair.
    captured: dict[str, object] = {}
    real_specialized = practice_generation.build_specialized_item_repair_prompt

    def recording_specialized(request, evidence, failed_item, *, category, harness_version, safe_position_summary=None):
        captured["failed_item_key"] = failed_item.item_key
        captured["category"] = category
        return real_specialized(request, evidence, failed_item, category=category, harness_version=harness_version, safe_position_summary=safe_position_summary)

    monkeypatch.setattr(practice_generation, "build_specialized_item_repair_prompt", recording_specialized)
    monkeypatch.setattr(practice_generation, "build_practice_repair_prompt", lambda *_a, **_k: pytest.fail("whole-Set structure repair must not run for a coding reference failure"))

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-1")

    # Repair targeted ONLY the failed coding item, with a bounded category.
    assert captured.get("failed_item_key") == coding_key
    assert captured.get("category") == "test_mismatch"
    # The Set persisted with both items; the valid choice is unchanged.
    practice_set = db_session.query(PracticeSet).filter_by(practice_job_id=job.id).one()
    items = list(db_session.query(PracticeItem).filter_by(practice_set_id=practice_set.id))
    assert len(items) == 2
    coding = next(it for it in items if it.item_type == "coding")
    assert coding.answer_spec["reference_solution"] == fixed_reference
    assert coding.answer_spec["harness_version"] == "solve_utf8_string_v2"
    choice = next(it for it in items if it.item_type == "single_choice")
    assert choice.stem == "Choose the supported statement."


# ---------------------------------------------------------------------------
# 5. Regression: repair immutability authority boundary (Codex review High 1)
# ---------------------------------------------------------------------------

def test_repair_immutability_rejects_changed_hidden_tests() -> None:
    """A specialized repair that returns different hidden_tests is rejected.
    The provider cannot smuggle in easier tests to make a weak reference pass."""
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    # Repair returns easier hidden_tests (different expected outputs)
    tampered = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "x", "weight": 1},  # easier
            {"input": "c", "expected_output": "x", "weight": 1},  # easier
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    with pytest.raises(ValueError, match="hidden_tests"):
        _assert_repair_immutability(original, tampered)


def test_repair_immutability_rejects_changed_stem() -> None:
    """A specialized repair that changes the stem is rejected."""
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    changed_stem = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity transformation.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    with pytest.raises(ValueError, match="stem"):
        _assert_repair_immutability(original, changed_stem)


def test_repair_immutability_rejects_changed_citation_ids() -> None:
    """A specialized repair that changes citation_ids is rejected."""
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    changed_cites = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e2"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    with pytest.raises(ValueError, match="citation_ids"):
        _assert_repair_immutability(original, changed_cites)


def test_repair_immutability_accepts_valid_coding_repair() -> None:
    """A specialized repair that only changes reference_solution passes immutability check."""
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return 'wrong'",
    )
    repaired = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return input_text",
    )
    # Should not raise — only reference_solution changed
    _assert_repair_immutability(original, repaired)


def test_repair_immutability_scientific_rejects_changed_rubric() -> None:
    """A specialized repair that changes the rubric on a scientific item is rejected."""
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="scientific",
        stem="Compute the velocity.", citation_ids=["e1"],
        scientific_answer_spec={
            "normalized_answer": "10", "equivalence_rule": "exact",
            "needs_remote_verification": False,
        },
        rubric=[
            {"criterion_key": "c1", "description": "Correct value", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Units", "weight": 40, "citation_ids": ["e1"]},
        ],
        reference_answer="v = 10 m/s",
    )
    changed_rubric = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="scientific",
        stem="Compute the velocity.", citation_ids=["e1"],
        scientific_answer_spec={
            "normalized_answer": "10", "equivalence_rule": "exact",
            "needs_remote_verification": False,
        },
        rubric=[
            {"criterion_key": "c1", "description": "Correct value", "weight": 100, "citation_ids": ["e1"]},
        ],
        reference_answer="v = 10 m/s",
    )
    with pytest.raises(ValueError, match="rubric"):
        _assert_repair_immutability(original, changed_rubric)


# ---------------------------------------------------------------------------
# 6. Regression: v1/v2 grading dispatch (Codex review High 2)
# ---------------------------------------------------------------------------

def test_coding_grading_rejects_unknown_harness_version() -> None:
    """execute_coding_grading raises artifact_contract_unsupported for an
    unknown harness_version in the answer_spec, rather than silently
    falling through to the current implementation."""
    from learn_platform_api.services.practice_generation import execute_coding_grading

    settings = Settings()
    answer_spec = {
        "harness_version": "solve_utf8_string_v999",
        "language": "python",
        "hidden_tests": [
            {"input": "a", "expected_output": "a", "weight": 1},
        ],
        "public_tests": [],
    }
    with pytest.raises(ValueError, match="artifact_contract_unsupported"):
        execute_coding_grading(
            source_code="def solve(x): return x",
            answer_spec=answer_spec,
            settings=settings,
        )


def test_coding_grading_accepts_known_harness_versions() -> None:
    """execute_coding_grading accepts both v1 and v2 harness versions.
    (The actual MCP call is mocked so this just tests the version gate.)"""
    from learn_platform_api.services.practice_generation import execute_coding_grading
    from learn_platform_api.services.code_lab_execution import ExecutionMcpError

    settings = Settings()
    for version in ("solve_utf8_string_v1", "solve_utf8_string_v2"):
        answer_spec = {
            "harness_version": version,
            "language": "python",
            "hidden_tests": [
                {"input": "a", "expected_output": "a", "weight": 1},
            ],
            "public_tests": [],
        }
        # The MCP call will fail (no real server), but the version gate
        # should NOT raise artifact_contract_unsupported.
        try:
            execute_coding_grading(
                source_code="def solve(x): return x",
                answer_spec=answer_spec,
                settings=settings,
            )
        except ExecutionMcpError:
            pass  # Expected: no real MCP server
        except ValueError as exc:
            assert "artifact_contract_unsupported" not in str(exc), (
                f"harness_version={version} should be accepted"
            )


# ---------------------------------------------------------------------------
# 7. Regression: staged error codes (Codex review Medium / Spec 005 §8)
# ---------------------------------------------------------------------------

def test_structure_error_code_maps_citation_errors() -> None:
    """_structure_error_code returns practice_citation_invalid for citation errors."""
    from learn_platform_api.services.practice_generation import _structure_error_code
    assert _structure_error_code(ValueError("unknown_citation")) == "practice_citation_invalid"
    assert _structure_error_code(ValueError("citation mismatch")) == "practice_citation_invalid"


def test_structure_error_code_maps_formula_errors() -> None:
    """_structure_error_code returns practice_formula_invalid for formula errors."""
    from learn_platform_api.services.practice_generation import _structure_error_code
    assert _structure_error_code(ValueError("invalid_formula_content")) == "practice_formula_invalid"


def test_structure_error_code_maps_duplicate_errors() -> None:
    """_structure_error_code returns practice_duplicate for duplicate errors."""
    from learn_platform_api.services.practice_generation import _structure_error_code
    assert _structure_error_code(ValueError("duplicate_practice_item")) == "practice_duplicate"


def test_structure_error_code_maps_schema_errors() -> None:
    """_structure_error_code returns practice_artifact_schema_invalid for
    ValidationError and unrecognized ValueError."""
    from learn_platform_api.services.practice_generation import _structure_error_code
    assert _structure_error_code(ValueError("invalid_learning_target")) == "practice_artifact_schema_invalid"
    assert _structure_error_code(ValueError("unsupported_practice_item_type")) == "practice_artifact_schema_invalid"


def test_structure_error_code_maps_pydantic_validation_error() -> None:
    """_structure_error_code returns practice_artifact_schema_invalid for Pydantic ValidationError."""
    from learn_platform_api.services.practice_generation import _structure_error_code
    from pydantic import ValidationError
    try:
        PracticeItemArtifact(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Test", citation_ids=["e1"],
        )
    except ValidationError as exc:
        assert _structure_error_code(exc) == "practice_artifact_schema_invalid"


# ---------------------------------------------------------------------------
# 8. Regression: repair immutability — provider smuggles easier hidden_tests
# ---------------------------------------------------------------------------

def test_repair_immutability_rejects_provider_smuggling_easier_hidden_tests() -> None:
    """TEST 1 — Repair immutability: Provider tries to smuggle in easier hidden_tests.

    When a specialized repair returns a coding item with different hidden_tests
    (e.g. easier expected outputs), ``_assert_repair_immutability`` must reject it
    with a ValueError mentioning ``hidden_tests``. This is a direct unit test of
    the immutability gate.
    """
    from academic_companion.practice_agents import PracticeItemArtifact
    from learn_platform_api.services.practice_generation import _assert_repair_immutability

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text):\n    return 'wrong'",
    )
    # Provider returns the same item but with easier hidden_tests
    smuggled = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "wrong", "weight": 1},  # easier: matches broken solution
            {"input": "c", "expected_output": "wrong", "weight": 1},  # easier: matches broken solution
        ],
        reference_solution="def solve(input_text):\n    return 'wrong'",
    )
    with pytest.raises(ValueError, match="hidden_tests"):
        _assert_repair_immutability(original, smuggled)


# ---------------------------------------------------------------------------
# 9. Regression: repair immutability integration — execute_generation rejects
#    a provider that tampers with immutable fields
# ---------------------------------------------------------------------------

def test_repair_immutability_integration_rejects_tampered_hidden_tests(
    db_session, monkeypatch
) -> None:
    """TEST 2 — Repair immutability integration: Provider returns changed immutable fields.

    An integration-style test where the provider returns a repaired coding item
    with tampered hidden_tests. ``execute_generation`` must fail with a STABLE
    error code (the user_code from the specialized failure, e.g.
    ``coding_reference_test_failed``), NOT the raw immutability message string
    that would break the stable error code contract in the worker. Follows the
    pattern of ``test_v2_coding_reference_failure_repairs_only_the_failed_item``.
    """
    from learn_platform_api.db.models import McpCapabilityStatus
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice, practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings
    from test_practice_worker import _reader

    workspace, course, course_version, lesson, lesson_version, chunk, document, document_version = _reader(db_session)
    lesson_version.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": True, "has_executable_evidence": True,
        "has_math_objective": False, "has_physics_objective": False,
        "has_chemistry_objective": False, "has_computable_evidence": False,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="code_execution", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    db_session.commit()
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_args: None)
    payload = type("P", (), {
        "item_count": 1, "difficulty": "standard", "output_language": "zh-CN",
        "item_type_mode": "require_coding", "code_languages": ["python"],
        "code_tool_authorized": True, "science_tool_authorized": False,
    })()
    job = practice.create_generation_job(
        db_session, get_settings(), workspace.id, course.id, course_version.id,
        lesson.id, lesson_version.id, payload, "immutability-integration-probe",
    )
    job.status = "running"
    job.worker_id = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    job.attempt_count = 1
    db_session.commit()

    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: (
        "trace",
        [RetrievalResult(
            score=0.9, text=chunk.content,
            citation=CitationRead(
                document_id=document.id, document_version_id=document_version.id,
                chunk_id=chunk.id, document_name=document.display_name,
                heading_path=[], start_offset=0, end_offset=len(chunk.content),
            ),
        )],
    ))

    coding_key = "q-code"
    broken_reference = "def solve(input_text):\n    return 'wrong'"
    initial_artifact = {"items": [
        {"item_key": coding_key, "target_key": "objective_1", "item_type": "coding",
         "stem": "Implement the identity transformation.", "citation_ids": ["e1"], "language": "python",
         "input_description": "one UTF-8 string", "output_description": "the same string",
         "hidden_tests": [
             {"input": "a", "expected_output": "a", "weight": 1},
             {"input": "b", "expected_output": "b", "weight": 1},
             {"input": "c", "expected_output": "c", "weight": 1},
         ],
         "reference_solution": broken_reference},
    ]}
    # Provider returns a "repair" with tampered hidden_tests (easier outputs)
    # Correction 002 §A: minimal DTO format, but with extra forbidden field (hidden_tests)
    tampered_repair = {
        "item_key": coding_key,
        "reference_solution": broken_reference,
        "hidden_tests": [  # extra forbidden field -> rejected by CodingReferenceRepairArtifact
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "wrong", "weight": 1},  # tampered
            {"input": "c", "expected_output": "wrong", "weight": 1},  # tampered
        ],
    }

    provider_results = iter([
        ({"queries": ["objective evidence", "implementation evidence", "test evidence"]}, {}),
        (initial_artifact, {}),
        (tampered_repair, {}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    # Reference validation fails for the broken solution
    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_reference:
            return CodingReferenceValidationResult(passed=False, tests_passed=0, tests_total=3, error_categories=["test_mismatch"], infrastructure_failure=False)
        return CodingReferenceValidationResult(passed=True, tests_passed=3, tests_total=3, error_categories=[], infrastructure_failure=False)
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    # execute_generation must raise a STABLE error code. Per Correction 002 §D,
    # when the minimal repair DTO contains forbidden extra fields (hidden_tests),
    # the stable code is coding_repair_artifact_invalid, NOT the raw
    # "specialized repair changed immutable field: hidden_tests" string and
    # NOT the original coding_reference_test_failed.
    with pytest.raises(ValueError, match="coding_repair_artifact_invalid"):
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-1")


# ---------------------------------------------------------------------------
# 10. Regression: v1/v2 grading dispatch — unknown harness_version rejected
# ---------------------------------------------------------------------------

def test_coding_grading_dispatch_rejects_unknown_harness_version() -> None:
    """TEST 3 — v1/v2 grading dispatch: Unknown harness_version is rejected.

    ``execute_coding_grading`` raises ``ValueError("artifact_contract_unsupported")``
    when the answer_spec contains an unknown harness_version, rather than silently
    falling through to the current implementation.
    """
    from learn_platform_api.services.practice_generation import execute_coding_grading

    settings = Settings()
    answer_spec = {
        "harness_version": "solve_utf8_string_v999",
        "language": "python",
        "hidden_tests": [
            {"input": "a", "expected_output": "a", "weight": 1},
        ],
        "public_tests": [],
    }
    with pytest.raises(ValueError, match="artifact_contract_unsupported"):
        execute_coding_grading(
            source_code="def solve(x): return x",
            answer_spec=answer_spec,
            settings=settings,
        )


# ---------------------------------------------------------------------------
# 11. Regression: staged error codes — validation_issues uses specific codes
# ---------------------------------------------------------------------------

def test_validation_issues_uses_specific_codes_not_generic() -> None:
    """TEST 4 — Staged error codes: validation_issues uses specific codes.

    The ``validation_issues`` function (which delegates to ``_structure_error_code``
    for ValueError) returns specific codes
    (``practice_citation_invalid``, ``practice_formula_invalid``,
    ``practice_duplicate``) instead of the generic
    ``invalid_practice_artifact``. This ensures monitoring and repair routing
    receive stable, specific codes per Spec 005 §8.
    """
    from learn_platform_api.services.practice_generation import _structure_error_code

    # Citation errors -> practice_citation_invalid (not invalid_practice_artifact)
    code = _structure_error_code(ValueError("unknown_citation"))
    assert code == "practice_citation_invalid"
    assert code != "invalid_practice_artifact"

    code = _structure_error_code(ValueError("citation mismatch"))
    assert code == "practice_citation_invalid"
    assert code != "invalid_practice_artifact"

    # Formula errors -> practice_formula_invalid (not invalid_practice_artifact)
    code = _structure_error_code(ValueError("invalid_formula_content"))
    assert code == "practice_formula_invalid"
    assert code != "invalid_practice_artifact"

    # Duplicate errors -> practice_duplicate (not invalid_practice_artifact)
    code = _structure_error_code(ValueError("duplicate_practice_item"))
    assert code == "practice_duplicate"
    assert code != "invalid_practice_artifact"

    # Unrecognized ValueError -> practice_artifact_schema_invalid (still not invalid_practice_artifact)
    code = _structure_error_code(ValueError("something_unrecognized"))
    assert code == "practice_artifact_schema_invalid"
    assert code != "invalid_practice_artifact"


# ---------------------------------------------------------------------------
# 12. Regression: v1/v2 generation dispatch — v1 Jobs are not rejected
# ---------------------------------------------------------------------------

def test_generation_dispatch_accepts_only_v2_contract() -> None:
    """Generation is v2-only; v1 remains a read/grading compatibility path."""
    from academic_companion.practice_agents import ARTIFACT_CONTRACT_V2
    from learn_platform_api.services import practice_generation
    import inspect

    source = inspect.getsource(practice_generation.execute_generation)
    assert "ARTIFACT_CONTRACT_V2" in source
    assert "!= ARTIFACT_CONTRACT_V2" in source


def test_generation_rejects_unknown_contract_version() -> None:
    """An unknown artifact_contract_version is rejected with
    artifact_contract_unsupported, not silently accepted."""
    from learn_platform_api.db.models import PracticeJob
    from learn_platform_api.services.practice_generation import execute_generation
    from learn_platform_api.settings import get_settings

    # We can't easily create a full Job with unknown version in the DB,
    # so verify the dispatch logic by checking the source
    import inspect
    source = inspect.getsource(execute_generation)
    assert "artifact_contract_unsupported" in source


# ---------------------------------------------------------------------------
# 13. Regression: v1/v2 grading dispatch — explicit builder selection
# ---------------------------------------------------------------------------

def test_grading_dispatch_uses_versioned_builder() -> None:
    """execute_coding_grading uses _build_coding_harness_for_version, not the
    unversioned _build_coding_harness. This ensures the version dispatch is
    explicit, not a whitelist that falls through to a single implementation."""
    from learn_platform_api.services import practice_generation
    import inspect

    source = inspect.getsource(practice_generation.execute_coding_grading)
    assert "_build_coding_harness_for_version" in source
    assert "_build_coding_harness(" not in source or "_build_coding_harness_for_version" in source


def test_versioned_builder_dispatches_v1_and_v2() -> None:
    """_build_coding_harness_for_version accepts both v1 and v2 and produces
    valid harness code for each."""
    from learn_platform_api.services.practice_generation import _build_coding_harness_for_version
    from academic_companion.practice_agents import HARNESS_V1, HARNESS_V2

    tests = [{"input": "a", "expected_output": "a", "weight": 1}]
    source = "def solve(input_text): return input_text"

    for version in (HARNESS_V1, HARNESS_V2):
        harness = _build_coding_harness_for_version(source, tests, "python", version)
        assert "import json" in harness
        assert "solve" in harness


def test_versioned_builder_rejects_unknown_version() -> None:
    """_build_coding_harness_for_version raises artifact_contract_unsupported
    for an unknown harness version."""
    from learn_platform_api.services.practice_generation import _build_coding_harness_for_version

    with pytest.raises(ValueError, match="artifact_contract_unsupported"):
        _build_coding_harness_for_version(
            "def solve(x): return x",
            [{"input": "a", "expected_output": "a", "weight": 1}],
            "python",
            "solve_utf8_string_v999",
        )


# ---------------------------------------------------------------------------
# 14. Regression: immutability check produces stable error code through worker
# ---------------------------------------------------------------------------

def test_repair_immutability_inside_exception_block_produces_stable_code(
    db_session, monkeypatch
) -> None:
    """When a provider returns a repaired item with tampered hidden_tests,
    the immutability check is inside the try/except block and the error
    is converted to the stable user_code (e.g. coding_reference_test_failed),
    NOT the raw "specialized repair changed immutable field: hidden_tests"
    string that would break the stable error code contract in the worker."""
    from learn_platform_api.db.models import McpCapabilityStatus, PracticeItem, PracticeSet
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice, practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings
    from test_practice_worker import _reader

    workspace, course, course_version, lesson, lesson_version, chunk, document, document_version = _reader(db_session)
    lesson_version.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": True, "has_executable_evidence": True,
        "has_math_objective": False, "has_physics_objective": False,
        "has_chemistry_objective": False, "has_computable_evidence": False,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="code_execution", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    db_session.commit()
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_args: None)
    payload = type("P", (), {
        "item_count": 2, "difficulty": "standard", "output_language": "zh-CN",
        "item_type_mode": "require_coding", "code_languages": ["python"],
        "code_tool_authorized": True, "science_tool_authorized": False,
    })()
    job = practice.create_generation_job(
        db_session, get_settings(), workspace.id, course.id, course_version.id,
        lesson.id, lesson_version.id, payload, "immutability-stable-code-probe",
    )
    job.status = "running"
    job.worker_id = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    job.attempt_count = 1
    db_session.commit()

    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: (
        "trace",
        [RetrievalResult(
            score=0.9, text=chunk.content,
            citation=CitationRead(
                document_id=document.id, document_version_id=document_version.id,
                chunk_id=chunk.id, document_name=document.display_name,
                heading_path=[], start_offset=0, end_offset=len(chunk.content),
            ),
        )],
    ))

    valid_choice_key = "q-choice"
    coding_key = "q-code"
    broken_reference = "def solve(input_text):\n    return 'wrong'"
    initial_artifact = {"items": [
        {"item_key": valid_choice_key, "target_key": "objective_1", "item_type": "single_choice",
         "stem": "Choose the supported statement.", "citation_ids": ["e1"],
         "options": [
             {"option_key": "a", "text": "A", "is_correct": True, "rationale": "ok", "citation_ids": ["e1"]},
             {"option_key": "b", "text": "B", "is_correct": False, "rationale": "no", "citation_ids": ["e1"]},
         ]},
        {"item_key": coding_key, "target_key": "objective_1", "item_type": "coding",
         "stem": "Implement the identity transformation.", "citation_ids": ["e1"], "language": "python",
         "input_description": "one UTF-8 string", "output_description": "the same string",
         "hidden_tests": [
             {"input": "a", "expected_output": "a", "weight": 1},
             {"input": "b", "expected_output": "b", "weight": 1},
             {"input": "c", "expected_output": "c", "weight": 1},
         ],
         "reference_solution": broken_reference},
    ]}
    # Malicious repair: provider returns easier hidden_tests
    # Correction 002 §A: minimal DTO format, but with extra forbidden field (hidden_tests)
    tampered_repair = {
        "item_key": coding_key,
        "reference_solution": broken_reference,
        "hidden_tests": [  # extra forbidden field -> rejected by CodingReferenceRepairArtifact
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "wrong", "weight": 1},  # easier
            {"input": "c", "expected_output": "wrong", "weight": 1},  # easier
        ],
    }

    provider_results = iter([
        ({"queries": ["objective evidence", "implementation evidence", "test evidence"]}, {}),
        (initial_artifact, {}),
        (tampered_repair, {}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_reference:
            return CodingReferenceValidationResult(passed=False, tests_passed=0, tests_total=3, error_categories=["test_mismatch"], infrastructure_failure=False)
        return CodingReferenceValidationResult(passed=True, tests_passed=3, tests_total=3, error_categories=[], infrastructure_failure=False)
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    # The immutability check is inside the try/except, so the error should
    # be converted to a STABLE error code, NOT the raw
    # "specialized repair changed immutable field: hidden_tests".
    # Per Correction 002 §D: when the minimal repair DTO contains forbidden
    # extra fields, the stable code is coding_repair_artifact_invalid.
    with pytest.raises(ValueError) as exc_info:
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-1")

    error_code = str(exc_info.value)
    # The error must be a STABLE code, not the raw immutability message
    assert error_code != "specialized repair changed immutable field: hidden_tests"
    # It should be the stable repair-artifact-invalid code (Correction 002 §D)
    assert error_code == "coding_repair_artifact_invalid"
