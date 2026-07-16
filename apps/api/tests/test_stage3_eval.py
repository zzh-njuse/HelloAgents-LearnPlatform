import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from stage3_eval import metrics, report, runner


REPO_ROOT = Path(__file__).resolve().parents[3]

# Keys that must never appear anywhere in an eval report. The assertion walks
# the full report JSON, so a forbidden field must be entirely absent rather than
# merely null.
FORBIDDEN_KEYS = {
    "prompt", "system_prompt", "system", "messages", "question", "answer", "answer_blocks",
    "draft", "blocks", "coverage_plan", "evidence", "chunk", "content", "text",
    "original_storage_uri", "parsed_storage_uri", "path", "file_path", "absolute_path",
    "input_hash", "tool_input", "provider", "model", "base_url", "api_key", "url",
    "connection", "log", "raw", "raw_response", "query", "queries", "sha256", "byte_size",
    "environment", "env", "idempotency_key", "worker_id", "key", "secret",
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
    # Every hard case must have an executable probe (no manifest-only promises).
    for entry in manifest["cases"]:
        assert entry["gate"] in {"hard", "observational"}
        assert runner.PROBES[entry["id"]] is not None


def test_metric_functions_are_pure_and_deterministic() -> None:
    assert metrics.outline_section_coverage([{"citation_ids": ["e1"]}, {"citation_ids": []}]) == 0.5
    assert metrics.outline_section_coverage([]) == 0.0
    assert metrics.block_citation_coverage([{"citation_ids": ["e1"]}, {"citation_ids": []}]) == 0.5
    assert metrics.evidence_duplication_ratio(["a", "a", "b"]) == pytest.approx(1 / 3)
    assert metrics.evidence_duplication_ratio([]) == 0.0
    rubric = metrics.empty_human_rubric()
    assert rubric == {"clarity": None, "relevance": None, "completeness": None}


def test_offline_runner_passes_hard_gates_and_writes_safe_report(tmp_path: Path) -> None:
    exit_code = runner.main(["--mode", "offline", "--report-dir", str(tmp_path)])
    assert exit_code == 0
    report_path = tmp_path / "stage3_eval_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == report.REPORT_SCHEMA_VERSION
    assert data["mode"] == "offline"
    assert data["manifest_version"]
    assert "generated_at" in data
    assert data["totals"]["hard_failed"] == 0
    assert data["totals"]["hard_passed"] == data["totals"]["hard_total"]
    assert data["totals"]["status"] == "passed"
    assert data["totals"]["observational_total"] >= 1

    # Per-case records carry only the allowed whitelist of keys.
    allowed_case_keys = {"id", "role", "gate", "status", "duration_ms", "error_category"}
    for entry in data["cases"]:
        assert set(entry.keys()) == allowed_case_keys
        assert entry["gate"] == "hard"

    allowed_observation_keys = {
        "case_id", "role", "status", "error_category", "duration_ms",
        "metrics", "human_rubric",
    }
    for entry in data["observational"]:
        assert set(entry.keys()) == allowed_observation_keys
        assert entry["status"] == "passed"
        assert entry["error_category"] is None

    # The report as a whole must not carry any forbidden field.
    leaked = _collect_keys(data) & FORBIDDEN_KEYS
    assert not leaked, f"forbidden fields leaked into report: {leaked}"


def test_offline_failure_exit_code_when_a_hard_gate_fails(tmp_path: Path, monkeypatch) -> None:
    # Force a single hard probe to violate its gate and confirm the runner exits
    # non-zero without losing the report.
    def failing_probe():
        raise runner.EvalFailure("citation_outside_snapshot", "forced failure")

    monkeypatch.setitem(runner.PROBES, "architect_single_source", failing_probe)
    exit_code = runner.main(["--mode", "offline", "--report-dir", str(tmp_path)])
    assert exit_code == 1
    data = json.loads((tmp_path / "stage3_eval_report.json").read_text(encoding="utf-8"))
    assert data["totals"]["hard_failed"] >= 1
    assert data["totals"]["status"] == "failed"
    failed = next(entry for entry in data["cases"] if entry["id"] == "architect_single_source")
    assert failed["status"] == "failed"
    assert failed["error_category"] == "citation_outside_snapshot"


def test_observational_failure_is_visible_but_nonblocking(tmp_path: Path, monkeypatch) -> None:
    def failing_probe():
        raise runner.EvalFailure("observation_failed")

    monkeypatch.setitem(runner.PROBES, "obs_course_outline", failing_probe)
    assert runner.main(["--mode", "offline", "--report-dir", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "stage3_eval_report.json").read_text(encoding="utf-8"))
    failed = next(entry for entry in data["observational"] if entry["case_id"] == "obs_course_outline")
    assert failed["status"] == "failed"
    assert failed["error_category"] == "observation_failed"
    assert failed["metrics"] is None


def test_report_schema_rejects_unapproved_metric_fields() -> None:
    with pytest.raises(ValidationError):
        report.build_report(
            manifest_version="test-v1",
            manifest_schema_version="1.0",
            mode="offline",
            case_results=[],
            observational=[{
                "case_id": "obs_course_outline",
                "role": "course_architect",
                "status": "passed",
                "error_category": None,
                "duration_ms": 1,
                "metrics": {"text": "must not enter a report"},
                "human_rubric": metrics.empty_human_rubric(),
            }],
            git_revision=None,
            generated_at="2026-07-16T00:00:00+00:00",
        )


def test_real_mode_without_confirmation_fails_closed(tmp_path: Path) -> None:
    exit_code = runner.main(["--mode", "real", "--report-dir", str(tmp_path)])
    assert exit_code != 0
    # No report is produced by a fail-closed real run.
    assert not (tmp_path / "stage3_eval_report.json").exists()


def test_real_mode_preview_does_not_call_provider(tmp_path: Path) -> None:
    exit_code = runner.main(["--mode", "real", "--preview", "--max-cases", "1", "--max-provider-calls", "12", "--report-dir", str(tmp_path)])
    assert exit_code == 0
    assert not (tmp_path / "stage3_eval_report.json").exists()


def test_real_mode_with_confirmation_still_fails_closed(tmp_path: Path) -> None:
    # Even with explicit confirmation and budgets, this slice does not wire an
    # actual provider adapter; it must stay fail-closed rather than fake success.
    exit_code = runner.main([
        "--mode", "real",
        "--ack-external-processing",
        "--max-cases", "1",
        "--max-provider-calls", "12",
        "--report-dir", str(tmp_path),
    ])
    assert exit_code != 0


def test_eval_report_directory_is_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/artifacts/eval/" in gitignore
    # The broader artifacts/ directory and the eval definitions are not ignored.
    assert "/artifacts/" not in gitignore.replace("/artifacts/eval/", "")
