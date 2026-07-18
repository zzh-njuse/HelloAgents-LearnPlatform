import { ArrowLeft, BookOpen, ClipboardCheck, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  cancelLearningJob, createRecomputeJob, createReviewAction, deleteLearningMemory, fetchLearningJob, fetchLearningMemories, fetchMemoryPolicy, patchLearningMemory, patchMemoryPolicy, retryLearningJob,
  fetchReviewItems, fetchLearningState, fetchWorkspaceLessonCompletions, LearningJobRead, LearningMemoryPolicyRead, LearningMemoryRead, LearningStateRead, LessonCompletion, ReviewItemRead,
} from "../lib/api";

const errorMessage = (value: unknown) => (value instanceof Error ? value.message : String(value));
const bandLabel = (band: string) => ({ insufficient: "证据不足", needs_review: "需要复习", developing: "学习中", secure: "较稳固" } as Record<string, string>)[band] ?? band;
const statusLabel = (status: string) => ({ due: "待复习", reviewing: "复习中", awaiting_validation: "等待验证", snoozed: "已稍后", dismissed: "已跳过", resolved: "已解决", provisional: "初步建议", confirmed: "已确认" } as Record<string, string>)[status] ?? status;

export type ReviewStudyTarget = { courseId: string; lessonId: string; mode: "content" | "practice"; setId?: string | null };

export function ReviewMemoryPanel({ workspaceId, onBack, onStudy }: { workspaceId: string; onBack?: () => void; onStudy?: (target: ReviewStudyTarget) => void }) {
  const [tab, setTab] = useState<"review" | "memory">("review");
  const [state, setState] = useState<LearningStateRead | null>(null);
  const [reviewItems, setReviewItems] = useState<ReviewItemRead[]>([]);
  const [memories, setMemories] = useState<LearningMemoryRead[]>([]);
  const [policy, setPolicy] = useState<LearningMemoryPolicyRead | null>(null);
  const [completions, setCompletions] = useState<LessonCompletion[]>([]);
  const [lessonFilter, setLessonFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [job, setJob] = useState<LearningJobRead | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [s, ri, mems, pol, completedLessons] = await Promise.all([
        fetchLearningState(workspaceId),
        fetchReviewItems(workspaceId),
        fetchLearningMemories(workspaceId),
        fetchMemoryPolicy(workspaceId),
        fetchWorkspaceLessonCompletions(workspaceId),
      ]);
      setState(s); setReviewItems(ri); setMemories(mems); setPolicy(pol); setCompletions(completedLessons);
      setSelectedReviewId((current) => ri.some((item) => item.id === current) ? current : ri[0]?.id ?? null);
    } catch (value) { setError(errorMessage(value)); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!job || !["queued", "running", "retry_wait", "cancel_requested"].includes(job.status)) return;
    const timer = window.setInterval(() => void fetchLearningJob(workspaceId, job.id).then((next) => {
      setJob(next);
      if (next.status === "succeeded") void refresh();
    }).catch((value) => { window.clearInterval(timer); setError(errorMessage(value)); }), 1000);
    return () => window.clearInterval(timer);
  }, [job, refresh, workspaceId]);

  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setError(null); try { await fn(); await refresh(); } catch (value) { setError(errorMessage(value)); } finally { setBusy(false); } };

  const dueCount = reviewItems.filter((item) => item.status === "due" || item.status === "reviewing").length;
  const memoryActiveCount = memories.filter((m) => m.status === "active").length;
  const selectedReview = reviewItems.find((item) => item.id === selectedReviewId) ?? null;
  const selectedTarget = state?.targets.find((target) => target.target_id === selectedReview?.target_id) ?? null;
  const selectedMemories = memories.filter((memory) => memory.lesson_id === selectedReview?.lesson_id);
  const lessonOptions = Array.from(new Map<string, string>([
    ...memories.map((item): [string, string] => [item.lesson_id, item.lesson_title]),
    ...completions.map((item): [string, string] => [item.lesson_id, item.lesson_title]),
  ])).filter(([id]) => id);
  const visibleMemories = memories.filter((memory) => (!lessonFilter || memory.lesson_id === lessonFilter) && (showArchived || memory.status !== "archived"));
  const visibleCompletions = completions.filter((item) => !lessonFilter || item.lesson_id === lessonFilter);

  const startStudy = async (mode: "content" | "practice") => {
    if (!selectedReview || !onStudy) return;
    setBusy(true); setError(null);
    try {
      if (selectedReview.status === "due" || selectedReview.status === "snoozed") {
        await createReviewAction(workspaceId, selectedReview.id, "reviewing");
      }
      onStudy({ courseId: selectedReview.course_id, lessonId: selectedReview.lesson_id, mode, setId: mode === "practice" ? selectedReview.source_set_id : null });
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  return <section className="review-memory-panel" aria-label="复习与记忆">
    <header className="review-memory-header">
      {onBack ? <button className="secondary-button" onClick={onBack} type="button"><ArrowLeft size={15} />返回学习</button> : null}
      <div className="review-memory-tabs">
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")} type="button">复习队列{dueCount ? ` (${dueCount})` : ""}</button>
        <button className={tab === "memory" ? "active" : ""} onClick={() => setTab("memory")} type="button">学习记忆{memoryActiveCount ? ` (${memoryActiveCount})` : ""}</button>
      </div>
      <button aria-label="刷新" className="icon-button" disabled={busy} onClick={() => void refresh()} title="刷新" type="button">{busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}</button>
      <button className="secondary-button" disabled={busy || Boolean(job && ["queued", "running", "retry_wait", "cancel_requested"].includes(job.status))} onClick={() => void act(async () => setJob(await createRecomputeJob(workspaceId)))} type="button">重算学习状态</button>
    </header>

    {job ? <div className="learning-job-status" role="status"><span>重算任务：{statusLabel(job.status)}</span>{job.error_message ? <span className="form-error">{job.error_message}</span> : null}{["queued", "running", "retry_wait"].includes(job.status) ? <button className="secondary-button" onClick={() => void act(async () => setJob(await cancelLearningJob(workspaceId, job.id)))} type="button">取消</button> : null}{["failed", "queue_failed", "canceled"].includes(job.status) ? <button className="secondary-button" onClick={() => void act(async () => setJob(await retryLearningJob(workspaceId, job.id)))} type="button">重试</button> : null}</div> : null}

    {loading ? <p className="muted"><LoaderCircle className="spin" size={16} /> 正在加载复习状态...</p> : null}

    {tab === "review" && !loading ? <div className="review-focus-grid">
      <aside className="review-queue" aria-label="复习队列">
      {reviewItems.length === 0 ? <p className="muted">暂无待复习内容。完成练习后，薄弱知识点会出现在这里。</p> : null}
      {reviewItems.map((item) => <button className={`review-queue-item${item.id === selectedReviewId ? " active" : ""}`} key={item.id} onClick={() => setSelectedReviewId(item.id)} type="button">
        <div className="review-card-head">
          <strong>{item.target_title}</strong>
          <span className={`review-status ${item.weakness_status}`}>{statusLabel(item.weakness_status)}</span>
        </div>
        <div className="review-card-meta">
          <small>状态：{statusLabel(item.status)}</small>
          {item.due_at ? <small>到期：{new Date(item.due_at).toLocaleDateString("zh-CN")}</small> : null}
        </div>
      </button>)}
      </aside>
      <main className="review-current">
        {selectedReview ? <>
          <p className="eyebrow">当前复习</p>
          <h2>{selectedReview.target_title}</h2>
          <p>你近期在“{selectedReview.target_title}”相关练习中出现了薄弱表现。先回看课节内容，再通过新练习验证是否掌握；仅点击“完成复习”不会提高掌握度。</p>
          <div className="review-card-actions">
            <button className="primary-button" disabled={busy || !onStudy} onClick={() => void startStudy("content")} type="button"><BookOpen size={15} />回看课节内容</button>
            <button className="secondary-button" disabled={busy || !onStudy || !selectedReview.source_set_id} onClick={() => void startStudy("practice")} type="button"><ClipboardCheck size={15} />回看出错练习</button>
            {selectedReview.status === "reviewing" ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => createReviewAction(workspaceId, selectedReview.id, "reviewed"))} type="button">完成复习</button> : null}
            <button className="secondary-button" disabled={busy} onClick={() => void act(() => createReviewAction(workspaceId, selectedReview.id, "snooze", 7))} type="button">7 天后提醒</button>
            <button className="secondary-button" disabled={busy} onClick={() => void act(() => createReviewAction(workspaceId, selectedReview.id, "dismiss"))} type="button">不适用</button>
          </div>
        </> : <p className="muted">从左侧选择一个复习项。</p>}
      </main>
      <aside className="review-evidence" aria-label="推荐依据">
        <h3>推荐依据</h3>
        {selectedTarget ? <>
          <p><strong>{bandLabel(selectedTarget.band)}</strong></p>
          <p className="muted">确定性信号 {selectedTarget.deterministic_signal_count} 条，AI 评分信号 {selectedTarget.ai_signal_count} 条。</p>
          <p className="muted">证据 {selectedTarget.evidence_count} 条{selectedTarget.last_evidence_at ? `，最后验证 ${new Date(selectedTarget.last_evidence_at).toLocaleDateString("zh-CN")}` : ""}。</p>
          {selectedTarget.source_degraded ? <p className="form-error">课程资料已变化，此项需要重新确认。</p> : null}
          {selectedReview?.source_item_ordinal ? <p className="muted">来源：{selectedReview.lesson_title} · 第 {selectedReview.source_item_ordinal} 题 · {selectedReview.source_is_ai ? "AI 评分" : "确定性判定"}{selectedReview.source_occurred_at ? ` · ${new Date(selectedReview.source_occurred_at).toLocaleString("zh-CN")}` : ""}</p> : null}
        </> : <p className="muted">暂无可展示的安全证据摘要。</p>}
        <h3>相关学习记忆</h3>
        {selectedMemories.length ? selectedMemories.map((memory) => <p className="memory-text" key={memory.id}>{memory.display_text}</p>) : <p className="muted">暂无相关记忆。</p>}
      </aside>
      {state ? <div className="mastery-summary">
        <strong>掌握度概览</strong>
        <div className="mastery-bands">
          {Object.entries(state.summary).map(([band, count]) => <span key={band} className={`band-${band}`}>{bandLabel(band)}: {count}</span>)}
        </div>
      </div> : null}
    </div> : null}

    {tab === "memory" ? <div className="memory-list">
      {memories.length === 0 ? <p className="muted">暂无学习记忆。系统会在薄弱点被确认后自动创建。</p> : null}
      {policy ? <div className="memory-policy-row">
        <label className="source-choice"><input checked={policy.tutor_use_enabled} onChange={(event) => void act(() => patchAndRefresh(workspaceId, event.target.checked, setPolicy))} type="checkbox" /><span>允许 Tutor 使用学习记忆（开启后摘要可能发送给外部 AI）</span></label>
      </div> : null}
      <div className="memory-filter-row"><label>课节<select onChange={(event) => setLessonFilter(event.target.value)} value={lessonFilter}><option value="">全部课节</option>{lessonOptions.map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label><label className="source-choice"><input checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} type="checkbox" />显示已归档记忆</label></div>
      <section className="completion-memory-section"><h3>学习进度 · 已完成课节 {visibleCompletions.length}</h3>{visibleCompletions.length ? visibleCompletions.map((item) => <div className="completion-memory-row" key={item.id}><strong>{item.lesson_title}</strong><span>{item.is_current_version ? "当前版本已完成" : "历史版本已完成，当前内容已更新"}</span><small>{new Date(item.completed_at).toLocaleString("zh-CN")}</small></div>) : <p className="muted">当前筛选范围还没有课节完成记录。</p>}</section>
      <h3>薄弱点记忆 · {visibleMemories.length}</h3>
      {visibleMemories.map((mem) => <article className="memory-card" key={mem.id}>
        <div className="memory-card-head">
          <strong>{mem.target_title}</strong>
          <span className={`memory-status ${mem.status}`}>{statusLabel(mem.status)}</span>
        </div>
        <p className="memory-text">{mem.display_text}</p>
        <div className="memory-card-meta">
          {mem.confirmed_at ? <small>确认于 {new Date(mem.confirmed_at).toLocaleDateString("zh-CN")}</small> : null}
          {mem.last_supported_at ? <small>最后支持 {new Date(mem.last_supported_at).toLocaleDateString("zh-CN")}</small> : null}
          <small>来源 {mem.source_count} 条</small>
          {mem.sources.slice(0, 3).map((source) => <small key={source.attempt_id}>{mem.lesson_title} · 第 {source.item_number} 题 · {source.is_ai ? "AI 评分" : "确定性判定"}</small>)}
        </div>
        <div className="memory-card-actions">
          <button className="secondary-button" disabled={busy} onClick={() => { const text = window.prompt("编辑说明", mem.display_text); if (text !== null) void act(() => patchLearningMemory(workspaceId, mem.id, { action: "edit", display_text: text })); }} type="button">编辑</button>
          {mem.status === "active" ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => patchLearningMemory(workspaceId, mem.id, { action: "pause" }))} type="button">暂停</button> : null}
          {mem.status === "paused" || mem.status === "needs_review" ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => patchLearningMemory(workspaceId, mem.id, { action: "reconfirm" }))} type="button">重新确认仍然适用</button> : null}
          <button className="secondary-button" disabled={busy} onClick={() => void act(() => patchLearningMemory(workspaceId, mem.id, { action: "archive" }))} title="从日常记忆中移除并停止提供给 Tutor；不会删除练习历史" type="button">不再使用</button>
          <button className="icon-button" disabled={busy} onClick={() => { if (window.confirm("硬删除此记忆？这不删除练习历史，未来新证据可能重新建立。")) void act(() => deleteLearningMemory(workspaceId, mem.id)); }} title="删除" type="button"><Trash2 size={15} /></button>
        </div>
      </article>)}
    </div> : null}

    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </section>;
}

async function patchAndRefresh(workspaceId: string, enabled: boolean, setPolicy: (p: LearningMemoryPolicyRead) => void) {
  setPolicy(await patchMemoryPolicy(workspaceId, enabled));
}
