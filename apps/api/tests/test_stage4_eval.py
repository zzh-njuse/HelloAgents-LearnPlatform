import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from stage4_eval import metrics, report, runner

REPO_ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_KEYS = {
    "prompt", "stem", "question", "answer", "answer_payload", "option_rationales", "is_correct",
    "rationale", "reference_answer", "rubric", "feedback_blocks", "evidence", "content", "text",
    "correct_option_key", "answer_spec", "provider", "model", "base_url", "api_key", "path",
    "input_hash", "tool_input", "raw", "queries",
}


def _collect_keys(value, into=None):
    into = set() if into is None else into
    if isinstance(value, dict):
        into.update(value.keys())
        for nested in value.values():
            _collect_keys(nested, into)
    elif isinstance(value, list):
        for nested in value:
            _collect_keys(nested, into)
    return into


def test_manifest_and_probes_are_aligned() -> None:
    manifest = runner.load_manifest()
    assert manifest["manifest_version"]
    assert manifest["schema_version"] == report.REPORT_SCHEMA_VERSION
    manifest_ids = {entry["id"] for entry in manifest["cases"]}
    probe_ids = set(runner.PROBES.keys())
    assert manifest_ids == probe_ids, f"manifest/probe mismatch: {manifest_ids ^ probe_ids}"
    for entry in manifest["cases"]:
        assert entry["gate"] in {"hard", "observational"}
        assert runner.PROBES[entry["id"]] is not None


def test_metric_functions_are_pure_and_deterministic() -> None:
    assert metrics.item_type_counts([{"item_type": "single_choice"}, {"item_type": "short_answer"}]) == {"single_choice_count": 1, "short_answer_count": 1}
    assert metrics.citation_coverage([{"e1"}, set()]) == 0.5
    assert metrics.citation_coverage([]) == 0.0
    rubric = metrics.empty_human_rubric()
    assert set(rubric.keys()) == {"answerability", "ambiguity", "difficulty_match", "distractor_quality", "rubric_coverage", "feedback_clarity"}
    assert all(value is None for value in rubric.values())


def test_offline_runner_passes_hard_gates_and_writes_safe_report(tmp_path: Path) -> None:
    exit_code = runner.main(["--mode", "offline", "--report-dir", str(tmp_path)])
    assert exit_code == 0
    report_path = tmp_path / "stage4_eval_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == report.REPORT_SCHEMA_VERSION
    assert data["mode"] == "offline"
    assert data["totals"]["hard_failed"] == 0
    assert data["totals"]["hard_total"] > 0
    assert data["totals"]["hard_passed"] == data["totals"]["hard_total"]
    assert data["totals"]["status"] == "passed"
    assert data["totals"]["observational_total"] >= 1

    allowed_case_keys = {"id", "role", "gate", "status", "duration_ms", "error_category"}
    for entry in data["cases"]:
        assert set(entry.keys()) == allowed_case_keys
        assert entry["gate"] == "hard"

    allowed_obs_keys = {"case_id", "role", "status", "error_category", "duration_ms", "metrics", "human_rubric"}
    for entry in data["observational"]:
        assert set(entry.keys()) == allowed_obs_keys

    leaked = _collect_keys(data) & FORBIDDEN_KEYS
    assert not leaked, f"forbidden fields leaked into report: {leaked}"


def test_offline_failure_exit_code_when_a_hard_gate_fails(tmp_path: Path, monkeypatch) -> None:
    def failing_probe():
        raise runner.EvalFailure("answer_leak", "forced failure")

    monkeypatch.setitem(runner.PROBES, "single_correct", failing_probe)
    exit_code = runner.main(["--mode", "offline", "--report-dir", str(tmp_path)])
    assert exit_code == 1
    data = json.loads((tmp_path / "stage4_eval_report.json").read_text(encoding="utf-8"))
    assert data["totals"]["hard_failed"] >= 1
    failed = next(entry for entry in data["cases"] if entry["id"] == "single_correct")
    assert failed["status"] == "failed" and failed["error_category"] == "answer_leak"


def test_report_schema_rejects_unapproved_metric_fields() -> None:
    with pytest.raises(ValidationError):
        report.build_report(
            manifest_version="test-v1", manifest_schema_version="1.0", mode="offline", case_results=[],
            observational=[{"case_id": "obs_generation", "role": "exercise_author", "status": "passed", "error_category": None, "duration_ms": 1, "metrics": {"stem": "must not enter a report"}, "human_rubric": metrics.empty_human_rubric()}],
            git_revision=None, generated_at="2026-07-16T00:00:00+00:00",
        )


def test_real_mode_fails_closed(tmp_path: Path) -> None:
    assert runner.main(["--mode", "real", "--report-dir", str(tmp_path)]) != 0
    assert not (tmp_path / "stage4_eval_report.json").exists()
    assert runner.main(["--mode", "real", "--preview", "--report-dir", str(tmp_path)]) == 0
    assert not (tmp_path / "stage4_eval_report.json").exists()


def test_eval_report_directory_is_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/artifacts/eval/" in gitignore
