import { BotMessageSquare, LoaderCircle, RefreshCw, Send, Square, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cancelTutorTurn, CourseReader, createTutorSession, createTutorTurn, deleteTutorSession, fetchTutorSession, fetchTutorSessions, retryTutorTurn, TutorSession, tutorTurnEventsUrl } from "../lib/api";

const active = (status: string) => ["queued", "running", "retry_wait", "cancel_requested"].includes(status);
const errorMessage = (value: unknown) => value instanceof Error ? value.message : String(value);
const pageLabel = (start: number | null, end: number | null) => start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`;

export function TutorPanel({ workspaceId, reader, lessonId, onLessonId }: { workspaceId: string; reader: CourseReader; lessonId: string; onLessonId: (value: string) => void }) {
  const lessons = useMemo(() => reader.version.sections.flatMap((section) => section.lessons
    .filter((lesson) => lesson.published_version)
    .map((lesson) => ({ section, lesson, version: lesson.published_version! }))), [reader]);
  const [sessions, setSessions] = useState<TutorSession[]>([]);
  const [session, setSession] = useState<TutorSession | null>(null);
  const [scope, setScope] = useState<"lesson" | "course">("lesson");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const turnIdempotencyKey = useRef<string | null>(null);

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
      const current = session ?? await createTutorSession(workspaceId, reader.course.id, reader.version.id);
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

  return <aside className="tutor-panel" aria-label="课程 Tutor">
    <header><div><span className="eyebrow">受控 Tutor</span><h3><BotMessageSquare size={18} />课程问答</h3></div>{session ? <button className="icon-button" disabled={busy} onClick={() => void removeSession()} title="删除当前 Tutor Session" type="button"><Trash2 /></button> : null}</header>
    <div className="tutor-meta"><span>课程版本 {reader.version.version_number}</span><span>{session ? `${session.provider} / ${session.model}` : "尚未创建 Session"}</span></div>
    {sessions.length ? <select aria-label="Tutor Session" onChange={(event) => setSession(sessions.find((item) => item.id === event.target.value) ?? null)} value={sessionId ?? ""}>{sessions.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")}</option>)}</select> : null}
    <div className="scope-control"><button className={scope === "lesson" ? "active" : ""} onClick={() => setScope("lesson")} type="button">当前课节</button><button className={scope === "course" ? "active" : ""} onClick={() => setScope("course")} type="button">整门课程</button></div>
    {scope === "lesson" ? <select aria-label="Tutor 课节" onChange={(event) => onLessonId(event.target.value)} value={lessonId}>{lessons.map(({ lesson }) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}</select> : null}
    <div className="tutor-history">{visibleTurns.length ? visibleTurns.map((turn) => {
      const numbers = new Map(turn.citations.map((citation, index) => [citation.citation_id, index + 1]));
      return <article key={turn.id}><p className="tutor-question">{turn.question}</p>{turn.answer_blocks?.map((block) => <div className={`tutor-answer ${block.type}`} key={block.block_key}><p>{block.text}</p>{block.citation_ids.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</div>)}{turn.citations.map((citation) => <small className="tutor-citation" key={citation.citation_id}>{numbers.get(citation.citation_id)}. {[citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ")}</small>)}<footer><span>{turn.status}</span>{active(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => cancelTutorTurn(workspaceId, turn.id))} type="button"><Square size={13} />取消</button> : null}{["failed", "canceled", "queue_failed"].includes(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => retryTutorTurn(workspaceId, turn.id))} type="button"><RefreshCw size={13} />重试</button> : null}</footer>{turn.error_message ? <p className="form-error">{turn.error_message}</p> : null}</article>;
    }) : <p className="muted">当前范围还没有问答记录。</p>}</div>
    <form onSubmit={submit}><textarea maxLength={8000} onChange={(event) => setQuestion(event.target.value)} placeholder="输入问题" rows={3} value={question} /><button className="primary-button" disabled={busy || !question.trim() || (scope === "lesson" && !lessonId) || Boolean(latestTurn && active(latestTurn.status))} type="submit">{busy ? <LoaderCircle className="spin" /> : <Send />}发送</button></form>
    {!session ? <small>首次发送前将确认使用固定课程版本和当前 provider 处理问题、短期历史及资料片段。</small> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </aside>;
}
