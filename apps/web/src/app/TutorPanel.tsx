import { BotMessageSquare, LoaderCircle, RefreshCw, Send, Square, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cancelTutorTurn, CourseReader, createTutorSession, createTutorTurn, deleteTutorSession, deleteTutorTurn, fetchLearningMemories, fetchLessonCompletions, fetchMemoryPolicy, fetchTutorSession, fetchTutorSessions, fetchTutorSkill, retryTutorTurn, TutorSession, TutorTeachingSkill, tutorTurnEventsUrl } from "../lib/api";

const active = (status: string) => ["queued", "running", "retry_wait", "cancel_requested"].includes(status);
const errorMessage = (value: unknown) => value instanceof Error ? value.message : String(value);
const pageLabel = (start: number | null, end: number | null) => start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`;
const certaintyLabel = (certainty: string | null) => certainty === "confirmed" ? "已确认" : certainty === "provisional" ? "初步判断" : certainty === "insufficient" ? "证据不足" : certainty === "resolved" ? "已改善" : null;

export function TutorPanel({ workspaceId, reader, lessonId, onLessonId, onManageMemory }: { workspaceId: string; reader: CourseReader; lessonId: string; onLessonId: (value: string) => void; onManageMemory?: () => void }) {
  const lessons = useMemo(() => reader.version.sections.flatMap((section) => section.lessons
    .filter((lesson) => lesson.published_version)
    .map((lesson) => ({ section, lesson, version: lesson.published_version! }))), [reader]);
  const [sessions, setSessions] = useState<TutorSession[]>([]);
  const [session, setSession] = useState<TutorSession | null>(null);
  const [scope, setScope] = useState<"lesson" | "course">("lesson");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryCount, setMemoryCount] = useState(0);
  const [completionCount, setCompletionCount] = useState(0);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [skill, setSkill] = useState<TutorTeachingSkill | null>(null);
  const turnIdempotencyKey = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void fetchTutorSkill(workspaceId, controller.signal).then((capability) => setSkill(capability.teaching_skill)).catch(() => {
      if (!controller.signal.aborted) setSkill(null);
    });
    return () => controller.abort();
  }, [workspaceId]);

  const refreshSessions = useCallback(async () => {
    const items = await fetchTutorSessions(workspaceId, reader.course.id, reader.version.id);
    setSessions(items);
    setSession((current) => items.find((item) => item.id === current?.id) ?? items[0] ?? null);
  }, [reader.course.id, reader.version.id, workspaceId]);

  useEffect(() => {
    setSession(null);
    void refreshSessions().catch((value) => setError(errorMessage(value)));
  }, [lessons, refreshSessions]);

  const sessionId = session?.id;
  const latestTurn = session ? session.turns[session.turns.length - 1] : undefined;
  const latestTurnId = latestTurn?.id;
  const latestTurnStatus = latestTurn?.status;
  const selectedLesson = lessons.find((item) => item.lesson.id === lessonId);
  const visibleTurns = session?.turns.filter((turn) => scope === "course"
    ? turn.scope === "course"
    : turn.scope === "lesson" && turn.lesson_version_id === selectedLesson?.version.id) ?? [];
  const latestVisibleTurn = visibleTurns[visibleTurns.length - 1];
  useEffect(() => {
    void Promise.all([fetchLearningMemories(workspaceId), fetchLessonCompletions(workspaceId, reader.course.id), fetchMemoryPolicy(workspaceId)])
      .then(([memories, completions, policy]) => {
        setMemoryEnabled(policy.tutor_use_enabled);
        setMemoryCount(policy.tutor_use_enabled ? memories.filter((memory) => memory.status === "active" && memory.course_id === reader.course.id && (scope === "course" || memory.lesson_id === lessonId)).slice(0, 5).length : 0);
        setCompletionCount(policy.tutor_use_enabled ? completions.filter((completion) => completion.course_version_id === reader.version.id && (scope === "course" || completion.lesson_version_id === selectedLesson?.version.id)).slice(0, 10).length : 0);
      })
      .catch((value) => setError(errorMessage(value)));
  }, [lessonId, reader.course.id, reader.version.id, scope, selectedLesson?.version.id, workspaceId]);
  useEffect(() => {
    if (!sessionId || !latestTurnId || !latestTurnStatus || !active(latestTurnStatus)) return;
    const source = new EventSource(tutorTurnEventsUrl(workspaceId, latestTurnId));
    const refresh = () => void fetchTutorSession(workspaceId, sessionId).then(setSession).catch(() => undefined);
    ["turn.started", "turn.progress", "answer.delta", "citation.available", "turn.completed", "turn.failed", "turn.canceled"].forEach((name) => source.addEventListener(name, refresh));
    return () => source.close();
  }, [latestTurnId, latestTurnStatus, sessionId, workspaceId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!question.trim()) return; setBusy(true); setError(null);
    try {
      if (scope === "lesson" && !selectedLesson) throw new Error("请选择当前课程中的有效课节");
      let current = session;
      if (!current) {
        const accepted = window.confirm(memoryEnabled
          ? "问题、必要的课程资料片段，以及启用的学习记忆和课节完成摘要将发送给当前配置的外部 AI，所选教学方法会处理这些内容。是否继续？"
          : "问题和必要的课程资料片段将发送给当前配置的外部 AI，所选教学方法会处理这些内容。是否继续？");
        if (!accepted) return;
        current = await createTutorSession(workspaceId, reader.course.id, reader.version.id, true);
      }
      const selected = selectedLesson;
      turnIdempotencyKey.current ??= crypto.randomUUID();
      await createTutorTurn(workspaceId, current.id, scope === "course"
        ? { question: question.trim(), scope }
        : { question: question.trim(), scope, section_id: selected?.section.id, lesson_id: selected?.lesson.id, lesson_version_id: selected?.version.id }, turnIdempotencyKey.current);
      setSession(await fetchTutorSession(workspaceId, current.id));
      turnIdempotencyKey.current = null; setQuestion(""); await refreshSessions();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const mutateTurn = async (work: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await work(); if (sessionId) setSession(await fetchTutorSession(workspaceId, sessionId)); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const removeSession = async () => {
    if (!sessionId) return; setBusy(true); setError(null);
    try { await deleteTutorSession(workspaceId, sessionId); setSession(null); await refreshSessions(); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const removeTurn = async (turnId: string) => {
    if (!sessionId || !window.confirm("删除这条问答记录？问题、回答、引用和运行记录都将被永久删除。")) return;
    setBusy(true); setError(null);
    try {
      await deleteTutorTurn(workspaceId, turnId);
      setSession(await fetchTutorSession(workspaceId, sessionId));
      await refreshSessions();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  return <aside className="tutor-panel" aria-label="课程 Tutor">
    <header><div><span className="eyebrow">受控 Tutor</span><h3><BotMessageSquare size={18} />课程问答</h3></div>{session ? <button className="icon-button" disabled={busy} onClick={() => void removeSession()} title="删除当前 Tutor Session" type="button"><Trash2 /></button> : null}</header>
    <div className="tutor-meta"><span>课程版本 {reader.version.version_number}</span><span>{session ? `${session.provider} / ${session.model}` : "尚未创建 Session"}</span></div>
    <div className="tutor-skill-meta">教学方法：{skill ? `${skill.display_name} v${skill.version}` : "—"}</div>
    <div className="tutor-memory-status">{memoryEnabled ? <>当前范围可选 {memoryCount} 条薄弱点记忆、{completionCount} 条课节完成记录{latestVisibleTurn?.status === "succeeded" ? `；最近一次实际使用 ${latestVisibleTurn.memory_count} 条、${latestVisibleTurn.completion_count} 条` : ""}</> : "学习记忆与课节完成记录未用于 Tutor"}{onManageMemory ? <button className="text-button" onClick={onManageMemory} type="button">管理</button> : null}</div>
    {sessions.length ? <select aria-label="Tutor Session" onChange={(event) => setSession(sessions.find((item) => item.id === event.target.value) ?? null)} value={sessionId ?? ""}>{sessions.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")}</option>)}</select> : null}
    <div className="scope-control"><button className={scope === "lesson" ? "active" : ""} onClick={() => { turnIdempotencyKey.current = null; setScope("lesson"); }} type="button">当前课节</button><button className={scope === "course" ? "active" : ""} onClick={() => { turnIdempotencyKey.current = null; setScope("course"); }} type="button">整门课程</button></div>
    {scope === "lesson" ? <select aria-label="Tutor 课节" onChange={(event) => { turnIdempotencyKey.current = null; onLessonId(event.target.value); }} value={lessonId}>{lessons.map(({ lesson }) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}</select> : null}
    <div className="tutor-history">{visibleTurns.length ? visibleTurns.map((turn) => {
      const citations = turn.citations ?? [];
      const numbers = new Map(citations.map((citation, index) => [citation.citation_id, index + 1]));
      return <article key={turn.id}><p className="tutor-question">{turn.question}</p>{turn.answer_blocks?.map((block) => <div className={`tutor-answer ${block.type}`} key={block.block_key}><p>{block.type === "learning_diagnosis" && certaintyLabel(block.certainty) ? <strong className="certainty-marker">{certaintyLabel(block.certainty)}：</strong> : null}{block.text}</p>{block.citation_ids.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</div>)}{citations.map((citation) => <small className="tutor-citation" key={citation.citation_id}>{numbers.get(citation.citation_id)}. {[citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ")}</small>)}<footer><span className="tutor-skill-badge" title={turn.teaching_skill ? `${turn.teaching_skill.display_name} v${turn.teaching_skill.version}` : "Slice 3 前的历史 Turn"}>{turn.teaching_skill ? `${turn.teaching_skill.display_name} v${turn.teaching_skill.version}` : "基础 Tutor（历史）"}</span><span>{turn.status}</span>{active(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => cancelTutorTurn(workspaceId, turn.id))} type="button"><Square size={13} />取消</button> : <button className="icon-button" disabled={busy} onClick={() => void removeTurn(turn.id)} title="删除这条问答" type="button"><Trash2 size={14} /></button>}{["failed", "canceled", "queue_failed"].includes(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => retryTutorTurn(workspaceId, turn.id))} type="button"><RefreshCw size={13} />重试</button> : null}</footer>{turn.error_message ? <p className="form-error">{turn.error_message}</p> : null}</article>;
    }) : <p className="muted">当前范围还没有问答记录。</p>}</div>
    <form onSubmit={submit}><textarea maxLength={8000} onChange={(event) => { turnIdempotencyKey.current = null; setQuestion(event.target.value); }} placeholder="输入问题" rows={3} value={question} /><button className="primary-button" disabled={busy || !question.trim() || (scope === "lesson" && !selectedLesson) || Boolean(latestTurn && active(latestTurn.status))} type="submit">{busy ? <LoaderCircle className="spin" /> : <Send />}发送</button></form>
    {!session ? <small>首次发送前将确认使用固定课程版本和当前 provider 处理问题、短期历史及资料片段。</small> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </aside>;
}
