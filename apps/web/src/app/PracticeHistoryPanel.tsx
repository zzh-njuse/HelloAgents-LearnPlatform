import { History, LoaderCircle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CourseReader, deletePracticeAttempt, fetchPracticeAttempts, fetchPracticeSet, fetchPracticeSets, PracticeAttemptRead, PracticeSetListItem } from "../lib/api";

const errorMessage = (value: unknown) => (value instanceof Error ? value.message : String(value));
const GRADE_ACTIVE = ["grading", "retry_wait", "queued", "running", "cancel_requested"];
const statusLabel = (status: string) => ({
  succeeded: "已完成", grading: "评分中", queued: "排队中", running: "评分中", retry_wait: "等待重试",
  failed: "失败", queue_failed: "队列失败", canceled: "已取消", cancel_requested: "取消中",
} as Record<string, string>)[status] ?? status;

export interface PracticeHistoryPanelProps {
  workspaceId: string;
  reader: CourseReader;
  lessonId: string;
  setId: string;
  onSetId: (value: string) => void;
}

export function PracticeHistoryPanel({ workspaceId, reader, lessonId, setId, onSetId }: PracticeHistoryPanelProps) {
  const lessons = useMemo(() => reader.version.sections.flatMap((section) => section.lessons.filter((lesson) => lesson.published_version)), [reader]);
  const [sets, setSets] = useState<PracticeSetListItem[]>([]);
  const [attempts, setAttempts] = useState<Record<string, PracticeAttemptRead[]>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedLesson = lessons.find((lesson) => lesson.id === lessonId);
  const lessonVersionId = selectedLesson?.published_version?.id ?? "";

  const refreshSets = useCallback(async () => {
    if (!selectedLesson) { setSets([]); setAttempts({}); return; }
    try {
      const list = await fetchPracticeSets(workspaceId, reader.course.id, reader.version.id, selectedLesson.id, lessonVersionId);
      setSets(list);
      const keep = setId && list.some((item) => item.id === setId);
      onSetId(keep ? setId : (list[0]?.id ?? ""));
    } catch (value) { setError(errorMessage(value)); }
  }, [workspaceId, reader.course.id, reader.version.id, selectedLesson, lessonVersionId, onSetId, setId]);

  useEffect(() => { setAttempts({}); setError(null); void refreshSets(); }, [refreshSets]);

  const loadAttempts = useCallback(async (targetSetId: string) => {
    if (!targetSetId) { setAttempts({}); return; }
    const detail = await fetchPracticeSet(workspaceId, targetSetId);
    const entries = await Promise.all(detail.items.map((item) => fetchPracticeAttempts(workspaceId, item.id).catch(() => [])));
    const next: Record<string, PracticeAttemptRead[]> = {};
    detail.items.forEach((item, index) => { next[item.id] = entries[index]; });
    setAttempts(next);
  }, [workspaceId]);

  useEffect(() => { void loadAttempts(setId).catch((value) => setError(errorMessage(value))); }, [setId, loadAttempts]);

  const hasActive = Object.values(attempts).some((list) => list.some((attempt) => GRADE_ACTIVE.includes(attempt.status)));
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => { void loadAttempts(setId).catch(() => undefined); }, 2000);
    return () => window.clearInterval(timer);
  }, [hasActive, setId, loadAttempts]);

  const removeAttempt = async (attemptId: string) => {
    if (!window.confirm("删除这次作答？对应反馈与评分记录将一并清理。")) return;
    setBusy(true); setError(null);
    try { await deletePracticeAttempt(workspaceId, attemptId); await loadAttempts(setId); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const allAttempts = Object.values(attempts).flat();
  const completed = allAttempts.filter((attempt) => attempt.status === "succeeded").length;
  const degraded = sets.some((item) => item.source_degraded);

  return <aside className="practice-history-panel" aria-label="练习记录">
    <header><span className="eyebrow">练习记录</span><h3><History size={18} />作答历史</h3></header>
    <div className="practice-history-context"><strong>{reader.course.title}</strong>{selectedLesson ? <small>{selectedLesson.title}</small> : null}</div>
    {sets.length ? <select aria-label="练习集合记录" onChange={(event) => onSetId(event.target.value)} value={setId}>
      {sets.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.item_count} 题{item.source_degraded ? " · 来源已变化" : ""}</option>)}
    </select> : <p className="muted">该课节还没有练习集合。</p>}
    {degraded ? <p className="form-error">来源已变化：历史只读，不能作答、重做或重试评分。</p> : null}
    {sets.length ? <p className="muted">已完成 {completed} 次 · 共 {allAttempts.length} 次作答</p> : null}
    <div className="practice-history-list">
      {allAttempts.map((attempt) => (
        <article className="practice-history-item" key={attempt.id}>
          <span className="practice-history-status">{GRADE_ACTIVE.includes(attempt.status) ? <LoaderCircle className="spin" size={13} /> : null}{statusLabel(attempt.status)}{attempt.feedback ? ` · ${attempt.feedback.score ?? "—"} 分 · ${attempt.feedback.verdict}` : ""}</span>
          <small>第 {attempt.ordinal} 次 · {new Date(attempt.created_at).toLocaleString("zh-CN")}</small>
          {attempt.error_message ? <small className="form-error">{attempt.error_message}</small> : null}
          <button className="icon-button" disabled={busy} onClick={() => void removeAttempt(attempt.id)} title="删除这次作答" type="button"><Trash2 size={14} /></button>
        </article>
      ))}
      {allAttempts.length === 0 && sets.length ? <p className="muted">该集合还没有作答。</p> : null}
    </div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </aside>;
}
