import { ArrowLeft, ChevronLeft, ChevronRight, ClipboardList, Eye, EyeOff, ListChecks, LoaderCircle, Plus, RefreshCw, Send, Sparkles, Square, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  cancelPracticeJob, CourseReader, createPracticeSet, deletePracticeSet, fetchPracticeAttempt, fetchPracticeAttempts, fetchPracticeJob,
  fetchPracticeSet, fetchPracticeSets, PracticeAttemptRead, PracticeDifficulty, PracticeJobRead, PracticeSetListItem, PracticeSetRead,
  retryPracticeJob, submitPracticeAttempt,
} from "../lib/api";

const ACTIVE = ["queued", "running", "retry_wait", "cancel_requested"];
const GRADE_ACTIVE = ["grading", "retry_wait", "queued", "running", "cancel_requested"];
const errorMessage = (value: unknown) => (value instanceof Error ? value.message : String(value));
const pageLabel = (start: number | null, end: number | null) => (start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`);
const verdictLabel = (verdict: string) => ({ correct: "正确", partially_correct: "部分正确", incorrect: "不正确", ungradable: "无法评分" } as Record<string, string>)[verdict] ?? verdict;

type Drafts = Record<string, { option_key?: string; text?: string; ack: boolean }>;

export interface PracticePanelProps {
  workspaceId: string;
  reader: CourseReader;
  lessonId: string;
  onLessonId: (value: string) => void;
  setId: string;
  onSetId: (value: string) => void;
}

export function PracticePanel({ workspaceId, reader, lessonId, onLessonId, setId, onSetId }: PracticePanelProps) {
  const lessons = useMemo(() => reader.version.sections.flatMap((section) => section.lessons
    .filter((lesson) => lesson.published_version)
    .map((lesson) => ({ section, lesson, version: lesson.published_version! }))), [reader]);
  const [sets, setSets] = useState<PracticeSetListItem[]>([]);
  const [selectedSet, setSelectedSet] = useState<PracticeSetRead | null>(null);
  const [genJob, setGenJob] = useState<PracticeJobRead | null>(null);
  const [itemCount, setItemCount] = useState(5);
  const [difficulty, setDifficulty] = useState<PracticeDifficulty>("standard");
  const [outputLanguage, setOutputLanguage] = useState<"lesson" | "zh-CN" | "en">("lesson");
  const [ack, setAck] = useState(false);
  const [submissionAck, setSubmissionAck] = useState(false);
  const [answersHidden, setAnswersHidden] = useState(false);
  const [creatingNew, setCreatingNew] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [attempts, setAttempts] = useState<Record<string, PracticeAttemptRead[]>>({});
  const [currentOrdinal, setCurrentOrdinal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedLesson = lessons.find((item) => item.lesson.id === lessonId);
  const courseId = reader.course.id;
  const courseVersionId = reader.version.id;

  const refreshSets = useCallback(async () => {
    if (!selectedLesson) { setSets([]); return; }
    const items = await fetchPracticeSets(workspaceId, courseId, courseVersionId, selectedLesson.lesson.id, selectedLesson.version.id);
    setSets(items);
  }, [workspaceId, courseId, courseVersionId, selectedLesson]);

  // Lesson scope change: clear per-scope state and reload the set list.
  useEffect(() => {
    setSelectedSet(null); setGenJob(null); setCurrentOrdinal(0); setDrafts({}); setAttempts({}); setSubmissionAck(false); setAnswersHidden(false); setCreatingNew(false); setError(null);
    void refreshSets().catch((value) => setError(errorMessage(value)));
  }, [refreshSets]);

  const openSet = useCallback(async (targetSetId: string | null) => {
    if (!targetSetId) { setSelectedSet(null); return; }
    try {
      const detail = await fetchPracticeSet(workspaceId, targetSetId);
      setSelectedSet(detail);
      setCreatingNew(false);
      setCurrentOrdinal(0);
      setDrafts({});
      setSubmissionAck(false);
      setAnswersHidden(false);
      const entries = await Promise.all(detail.items.map((item) => fetchPracticeAttempts(workspaceId, item.id).catch(() => [])));
      const next: Record<string, PracticeAttemptRead[]> = {};
      detail.items.forEach((item, index) => { next[item.id] = entries[index]; });
      setAttempts(next);
    } catch (value) { setError(errorMessage(value)); }
  }, [workspaceId]);

  useEffect(() => {
    if (!creatingNew && !setId && !selectedSet && sets.length) onSetId(sets[0].id);
  }, [creatingNew, onSetId, selectedSet, setId, sets]);

  // Shared setId (driven by the right-side history) opens the matching set.
  useEffect(() => {
    if (!setId) { setSelectedSet(null); return; }
    if (selectedSet?.id !== setId) void openSet(setId);
  }, [setId, openSet, selectedSet?.id]);

  useEffect(() => {
    if (!genJob || !ACTIVE.includes(genJob.status)) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await fetchPracticeJob(workspaceId, genJob!.id);
        if (!active) return;
        setGenJob(next);
        if (next.status === "succeeded") {
          await refreshSets();
          if (next.practice_set_id) {
            setCreatingNew(false);
            onSetId(next.practice_set_id);
            await openSet(next.practice_set_id);
          }
        }
        if (ACTIVE.includes(next.status)) timer = window.setTimeout(() => void poll(), 1500);
      } catch (value) { if (active) setError(errorMessage(value)); }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [genJob, workspaceId, refreshSets, onSetId, openSet]);

  const generate = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedLesson || !ack) return;
    setBusy(true); setError(null);
    try {
      const job = await createPracticeSet(workspaceId, courseId, courseVersionId, selectedLesson.lesson.id, selectedLesson.version.id, {
        item_count: itemCount, difficulty, output_language: outputLanguage === "lesson" ? undefined : outputLanguage,
      });
      setGenJob(job); setAck(false);
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const submitPaper = async () => {
    if (sourceDegraded) return;
    const unanswered = items.filter((item) => attempts[item.id]?.length
      ? false
      : item.item_type === "single_choice" ? !drafts[item.id]?.option_key : !drafts[item.id]?.text?.trim());
    if (unanswered.length) {
      const unansweredNumbers = items.flatMap((item, index) => unanswered.includes(item) ? [index + 1] : []);
      if (!window.confirm(`第 ${unansweredNumbers.join("、")} 题尚未作答，仍要提前交卷吗？`)) return;
    }
    const pending = items.filter((item) => !attempts[item.id]?.length && !unanswered.includes(item));
    if (!pending.length) return;
    const needsExternalGrading = pending.some((item) => item.item_type === "short_answer");
    if (needsExternalGrading && !submissionAck) return;
    setBusy(true); setError(null);
    try {
      for (const item of pending) {
        const draft = drafts[item.id];
        const attempt = await submitPracticeAttempt(workspaceId, item.id, item.item_type === "single_choice"
          ? { external_processing_ack: false, option_key: draft.option_key }
          : { external_processing_ack: true, text: draft.text!.slice(0, 8000) });
        setAttempts((current) => ({ ...current, [item.id]: [attempt, ...(current[item.id] ?? [])] }));
      }
      setSubmissionAck(false);
      setAnswersHidden(false);
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const pollGrading = useCallback(async (itemId: string) => {
    const latest = attempts[itemId]?.[0];
    if (!latest || !GRADE_ACTIVE.includes(latest.status)) return;
    const next = await fetchPracticeAttempt(workspaceId, latest.id);
    setAttempts((current) => ({ ...current, [itemId]: [next, ...(current[itemId] ?? []).slice(1)] }));
  }, [attempts, workspaceId]);

  const hasActiveGrading = Object.values(attempts).some((list) => list.some((attempt) => GRADE_ACTIVE.includes(attempt.status)));
  useEffect(() => {
    if (!hasActiveGrading) return;
    const timer = window.setInterval(() => {
      Object.entries(attempts).forEach(([itemId, list]) => {
        if (list.some((attempt) => GRADE_ACTIVE.includes(attempt.status))) void pollGrading(itemId).catch(() => undefined);
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveGrading, attempts, pollGrading]);

  const removeSet = async () => {
    if (!selectedSet || !window.confirm("删除整个练习集合？题目、作答和反馈都会清理。")) return;
    setBusy(true); setError(null);
    try { await deletePracticeSet(workspaceId, selectedSet.id); setSelectedSet(null); onSetId(""); await refreshSets(); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const actJob = async (work: () => Promise<PracticeJobRead>) => {
    setBusy(true); setError(null);
    try { const job = await work(); setGenJob(job); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const items = selectedSet?.items ?? [];
  const currentItem = items[currentOrdinal];
  const latestAttempt = currentItem ? attempts[currentItem.id]?.[0] : undefined;
  const hasSubmittedAnswers = Object.values(attempts).some((list) => list.length > 0);
  const currentSubmitted = Boolean(currentItem && attempts[currentItem.id]?.length);
  const pendingShortAnswer = items.some((item) => item.item_type === "short_answer" && !attempts[item.id]?.length && Boolean(drafts[item.id]?.text?.trim()));
  const sourceDegraded = selectedSet?.source_degraded ?? false;
  const historicalSet = Boolean(selectedSet && selectedLesson && selectedSet.lesson_version_id !== selectedLesson.version.id);
  const readOnly = sourceDegraded; // source_degraded is fully read-only for practice

  return <section className="practice-panel" aria-label="课节练习">
    <header className="practice-header">
      <div><span className="eyebrow">练习</span><h3><ClipboardList size={18} />{reader.course.title} · 课节练习</h3></div>
      <select aria-label="练习课节" onChange={(event) => onLessonId(event.target.value)} value={lessonId}>
        {lessons.map(({ lesson }) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}
      </select>
    </header>

    {genJob ? <div className={`practice-job ${genJob.status === "failed" || genJob.status === "queue_failed" ? "failed" : ""}`} role="status">
      {ACTIVE.includes(genJob.status) ? <LoaderCircle className="spin" size={16} /> : null}
      <span>生成任务 · {reader.course.title} · {selectedLesson?.lesson.title ?? "课节"} · {itemCount} 题 · {genJob.status}</span>
      {genJob.error_message ? <small>{genJob.error_message}</small> : null}
      {ACTIVE.includes(genJob.status) && genJob.status !== "cancel_requested" ? <button className="secondary-button" disabled={busy} onClick={() => void actJob(() => cancelPracticeJob(workspaceId, genJob.id))} type="button"><Square size={14} />取消</button> : null}
      {["failed", "queue_failed", "canceled"].includes(genJob.status) ? <button className="secondary-button" disabled={busy} onClick={() => void actJob(() => retryPracticeJob(workspaceId, genJob.id))} type="button"><RefreshCw size={14} />重试</button> : null}
    </div> : null}

    {creatingNew || !selectedSet ? <form className="practice-generate" onSubmit={generate}>
      {creatingNew && setId ? <button className="secondary-button practice-return-button" onClick={() => void openSet(setId)} type="button"><ArrowLeft size={15} />返回当前练习</button> : null}
      <p className="muted">为「{reader.course.title} / {selectedLesson?.lesson.title ?? "当前课节"}」生成独立练习。默认 5 题，2 题及以上混合单选与简答。</p>
      <label className="practice-field">题数<input max={10} min={1} onChange={(event) => setItemCount(Number(event.target.value))} type="number" value={itemCount} /></label>
      <label className="practice-field">难度<select onChange={(event) => setDifficulty(event.target.value as PracticeDifficulty)} value={difficulty}><option value="easy">基础</option><option value="standard">标准</option><option value="hard">挑战</option></select></label>
      <label className="practice-field">语言<select onChange={(event) => setOutputLanguage(event.target.value as "lesson" | "zh-CN" | "en")} value={outputLanguage}><option value="lesson">沿用课节语言</option><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
      <label className="source-choice"><input checked={ack} disabled={readOnly} onChange={(event) => setAck(event.target.checked)} type="checkbox" />我同意将本课节相关资料发送给外部 AI 模型，用于生成练习题</label>
      <button className="primary-button" disabled={busy || !ack || !selectedLesson || readOnly || Boolean(genJob && ACTIVE.includes(genJob.status))} type="submit">{busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}生成练习</button>
      {readOnly ? <p className="form-error">课程来源已变化：历史题目、作答与反馈仍可查看，但暂不能生成新练习。</p> : null}
    </form> : null}

    {sets.length || selectedSet ? <div className="practice-set-toolbar"><label className="practice-set-picker"><span><ListChecks size={16} />练习记录</span><select aria-label="练习集合" onChange={(event) => { setCreatingNew(false); onSetId(event.target.value); }} value={selectedSet?.id ?? setId}>
      {historicalSet && selectedSet ? <option value={selectedSet.id}>历史课节版本 · {new Date(selectedSet.created_at).toLocaleString("zh-CN")}</option> : null}
      {sets.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.item_count} 题 · {item.difficulty === "easy" ? "基础" : item.difficulty === "hard" ? "挑战" : "标准"}{item.source_degraded ? " · 来源已变化" : ""}</option>)}
    </select></label><button className="secondary-button practice-new-button" disabled={busy || creatingNew} onClick={() => { setCreatingNew(true); setGenJob(null); setAck(false); }} type="button"><Plus size={15} />新建练习</button></div> : null}

    {historicalSet ? <p className="practice-history-notice" role="status">这是旧课节版本的练习，仅供回看当时的题目、作答与反馈；新课节的练习记录不会包含它。</p> : null}

    {!creatingNew && selectedSet && currentItem ? <div className="practice-focus">
      <div className="practice-progress"><strong>第 {currentOrdinal + 1} / {items.length} 题</strong><small>{currentItem.item_type === "single_choice" ? "单选" : "简答"} · {selectedSet.difficulty === "easy" ? "基础" : selectedSet.difficulty === "hard" ? "挑战" : "标准"} · {selectedSet.output_language === "zh-CN" ? "简体中文" : "English"}</small>
        {selectedSet.source_degraded ? <small className="form-error">来源已变化：题目、作答与反馈只读，引用可能不可用，不能作答或重做。</small> : null}
      </div>
      <p className="practice-stem">{currentItem.stem}</p>
      {currentItem.item_type === "single_choice" ? <div className="practice-options">
        {currentItem.options?.map((option) => <label className={`practice-option ${!answersHidden && drafts[currentItem.id]?.option_key === option.option_key ? "selected" : ""}`} key={option.option_key}><input checked={!answersHidden && drafts[currentItem.id]?.option_key === option.option_key} disabled={busy || readOnly || currentSubmitted} onChange={() => setDrafts((current) => ({ ...current, [currentItem.id]: { ...current[currentItem.id], option_key: option.option_key, ack: false } }))} type="radio" name={`opt-${currentItem.id}`} />{option.text}</label>)}
      </div> : <textarea className="practice-textarea" disabled={busy || readOnly || currentSubmitted} maxLength={8000} onChange={(event) => setDrafts((current) => ({ ...current, [currentItem.id]: { ...current[currentItem.id], text: event.target.value } }))} placeholder="输入简答（最多 8000 字符）" rows={5} value={answersHidden ? "" : drafts[currentItem.id]?.text ?? ""} />}

      <div className="practice-actions">
        <button className="icon-button" disabled={currentOrdinal <= 0} onClick={() => setCurrentOrdinal((value) => value - 1)} title="上一题" type="button"><ChevronLeft size={18} /></button>
        <button className="icon-button" disabled={currentOrdinal >= items.length - 1} onClick={() => setCurrentOrdinal((value) => value + 1)} title="下一题" type="button"><ChevronRight size={18} /></button>
        {currentOrdinal === items.length - 1 ? <button className="primary-button" disabled={busy || readOnly || (pendingShortAnswer && !submissionAck)} onClick={() => void submitPaper()} type="button">{busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}交卷</button> : null}
        {hasSubmittedAnswers ? <button className="secondary-button" onClick={() => setAnswersHidden((value) => !value)} type="button">{answersHidden ? <Eye size={15} /> : <EyeOff size={15} />}{answersHidden ? "显示答案" : "遮挡答案"}</button> : null}
        <button className="secondary-button" disabled={busy} onClick={() => void removeSet()} type="button"><Trash2 size={15} />删除集合</button>
      </div>

      {currentOrdinal === items.length - 1 && pendingShortAnswer ? <label className="source-choice submission-consent"><input checked={submissionAck} disabled={readOnly || busy} onChange={(event) => setSubmissionAck(event.target.checked)} type="checkbox" />我同意将本次答卷和评分所需资料发送给外部 AI 模型进行评分</label> : null}

      {latestAttempt && !answersHidden ? <FeedbackView attempt={latestAttempt} workspaceId={workspaceId} citations={currentItem.citations} /> : null}
    </div> : null}

    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </section>;
}

type FeedbackCitation = { citation_key: string; document_name: string; heading_path: string[]; page_start: number | null; page_end: number | null };

const humanizeFeedbackText = (text: string, citations: FeedbackCitation[]) => {
  let result = text;
  for (const citation of citations) {
    const location = [citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ") || "下方引用资料";
    const escapedKey = citation.citation_key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(new RegExp(`\\b${escapedKey}\\b`, "gi"), location);
  }
  return result.replace(/\be\d+\b/gi, "下方引用资料");
};

export function FeedbackView({ attempt, citations }: { attempt: PracticeAttemptRead; workspaceId: string; citations: FeedbackCitation[] }) {
  const feedback = attempt.feedback;
  if (!feedback) {
    if (GRADE_ACTIVE.includes(attempt.status)) {
      return <div className="practice-feedback grading"><LoaderCircle className="spin" size={15} /><span>正在评分…</span></div>;
    }
    if (attempt.error_message) return <div className="practice-feedback failed"><span>{attempt.error_message}</span></div>;
    return null;
  }
  const numbers = new Map(feedback.citations.map((citation, index) => [citation.citation_key, index + 1]));
  return <div className={`practice-feedback verdict-${feedback.verdict}`}>
    <div className="practice-feedback-head"><strong>{verdictLabel(feedback.verdict)}</strong>{feedback.score != null ? <span>{feedback.score} 分</span> : null}{feedback.is_ai_graded ? <small>AI 反馈</small> : null}</div>
    {feedback.criterion_results.length ? <ul className="practice-rubric">{feedback.criterion_results.map((result) => <li key={result.criterion_key}><span>{result.met === "full" ? "✔" : result.met === "partial" ? "◑" : "✘"} {humanizeFeedbackText(result.note, citations)}</span></li>)}</ul> : null}
    {feedback.feedback_blocks.map((block) => <p className={`feedback-block ${block.type}`} key={block.block_key}>{humanizeFeedbackText(block.text, citations)}{block.citation_ids.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</p>)}
    {feedback.citations.length ? <div className="citation-list">{feedback.citations.map((citation) => <div key={citation.citation_key}><strong>{numbers.get(citation.citation_key)}. {[citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ")}</strong>{!citation.available ? <small>来源已不可用</small> : null}</div>)}</div> : null}
  </div>;
}
