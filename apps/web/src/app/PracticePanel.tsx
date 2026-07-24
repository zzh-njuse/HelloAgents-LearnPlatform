import { ArrowLeft, ChevronLeft, ChevronRight, ClipboardList, Eye, EyeOff, ListChecks, LoaderCircle, Maximize2, Minimize2, Play, Plus, RefreshCw, Send, Sparkles, Square, Terminal, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelPracticeJob, CourseReader, createPracticeSet, deletePracticeSet, fetchPracticeAttempt, fetchPracticeAttempts, fetchPracticeJob,
  fetchPracticeSet, fetchPracticeSets, PracticeAttemptRead, PracticeDifficulty, PracticeJobRead, PracticeSetListItem, PracticeSetRead,
  retryPracticeJob, submitPracticeAttempt, createCodeRun, getCodeRun, getMcpPolicy, patchMcpPolicy, CodeRunDetail, ScienceVerificationRead,
} from "../lib/api";
import CodeWorkbench from "./CodeWorkbench";
import RichLearningText from "./RichLearningText";

const ACTIVE = ["queued", "running", "retry_wait", "cancel_requested"];
const GRADE_ACTIVE = ["grading", "retry_wait", "queued", "running", "cancel_requested"];
const errorMessage = (value: unknown) => (value instanceof Error ? value.message : String(value));
const pageLabel = (start: number | null, end: number | null) => (start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`);
const verdictLabel = (verdict: string) => ({ correct: "正确", partially_correct: "部分正确", incorrect: "不正确", ungradable: "无法评分" } as Record<string, string>)[verdict] ?? verdict;

type Drafts = Record<string, { option_key?: string; text?: string; source_code?: string; ack: boolean }>;

const wrapPracticeSource = (language: "python" | "java" | "cpp", source: string) => {
  if (language === "java") {
    // Task E: strip `public` (and `public final`) from `class Solution` so the
    // product-generated `class Main` compiles alongside it in Main.java. This
    // handles `public class Solution`, `public final class Solution`, and
    // bare `class Solution`. The regex only matches the class declaration,
    // not occurrences inside strings or comments (it requires the token to
    // appear at the start of a line, preceded only by whitespace).
    const normalized = source.replace(/^(\s*)(public\s+)?(final\s+)?class\s+Solution\b/gm, "$1class Solution");
    return `${normalized}\nclass Main { public static void main(String[] args) throws Exception { String input = new String(System.in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8); System.out.print(Solution.solve(input)); } }`;
  }
  if (language === "cpp") return `#include <iostream>\n#include <iterator>\n#include <string>\n${source}\nint main() { std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>()); std::cout << solve(input); }`;
  return `${source}\n\nif __name__ == "__main__":\n    import sys\n    result = solve(sys.stdin.read())\n    if result is not None:\n        print(result, end="")`;
};

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
  // Slice 4 / Correction 011 §2: item type mode selector (Spec 004 §11.2)
  const [itemTypeMode, setItemTypeMode] = useState<"auto" | "general_only" | "require_coding" | "require_science">("auto");
  const [codeLanguages, setCodeLanguages] = useState<string[]>(["python"]);
  const [codeToolAuthorized, setCodeToolAuthorized] = useState(false);
  const [scienceToolAuthorized, setScienceToolAuthorized] = useState(false);
  const [ack, setAck] = useState(false);
  const [submissionAck, setSubmissionAck] = useState(false);
  const [answersHidden, setAnswersHidden] = useState(false);
  const [creatingNew, setCreatingNew] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [attempts, setAttempts] = useState<Record<string, PracticeAttemptRead[]>>({});
  const [currentOrdinal, setCurrentOrdinal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [codeFocused, setCodeFocused] = useState(false);
  const [scratchInputs, setScratchInputs] = useState<Record<string, string>>({});
  const [scratchRun, setScratchRun] = useState<CodeRunDetail | null>(null);
  const [scratchRunItemId, setScratchRunItemId] = useState<string | null>(null);
  // Task D §3/§4: snapshot of the (source_code, stdin) that produced the current
  // scratchRun. When the user edits source or stdin, the snapshot no longer
  // matches and the stale result is cleared. Late responses whose snapshot
  // doesn't match the current input are discarded.
  const [scratchRunInputSnapshot, setScratchRunInputSnapshot] = useState<string | null>(null);
  // Ref to track the current run's token for late-response discard. Each
  // invocation of runCurrentCode generates a unique token; if the user
  // changes inputs or switches items before the response arrives, the token
  // no longer matches and the response is silently dropped.
  const scratchRunTokenRef = useRef<string | null>(null);
  const [scratchBusy, setScratchBusy] = useState(false);
  const [codeExecutionEnabled, setCodeExecutionEnabled] = useState(false);
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

  useEffect(() => {
    void getMcpPolicy(workspaceId)
      .then((policy) => setCodeExecutionEnabled(policy.code_execution_enabled))
      .catch(() => setCodeExecutionEnabled(false));
  }, [workspaceId]);

  const changeCodeExecutionPolicy = async (enabled: boolean) => {
    setBusy(true); setError(null);
    try {
      const policy = await patchMcpPolicy(workspaceId, { code_execution_enabled: enabled });
      setCodeExecutionEnabled(policy.code_execution_enabled);
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

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
        item_type_mode: itemTypeMode,
        code_languages: codeToolAuthorized ? codeLanguages : undefined,
        code_tool_authorized: codeToolAuthorized,
        science_tool_authorized: scienceToolAuthorized,
      });
      setGenJob(job); setAck(false);
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const submitPaper = async () => {
    if (sourceDegraded) return;
    const unanswered = items.filter((item) => attempts[item.id]?.length
      ? false
      : item.item_type === "single_choice" ? !drafts[item.id]?.option_key
        : item.item_type === "coding" ? !(drafts[item.id]?.source_code ?? item.interaction_spec?.starter_code ?? "").trim()
        : !drafts[item.id]?.text?.trim());
    if (unanswered.length) {
      const unansweredNumbers = items.flatMap((item, index) => unanswered.includes(item) ? [index + 1] : []);
      if (!window.confirm(`第 ${unansweredNumbers.join("、")} 题尚未作答，仍要提前交卷吗？`)) return;
    }
    const pending = items.filter((item) => !attempts[item.id]?.length && !unanswered.includes(item));
    if (!pending.length) return;
    const needsExternalGrading = pending.some((item) => item.item_type !== "single_choice");
    if (needsExternalGrading && !submissionAck) return;
    setBusy(true); setError(null);
    try {
      for (const item of pending) {
        const draft = drafts[item.id];
        const attempt = await submitPracticeAttempt(workspaceId, item.id, item.item_type === "single_choice"
          ? { external_processing_ack: false, option_key: draft?.option_key }
          : item.item_type === "coding"
            ? { external_processing_ack: true, source_code: (draft?.source_code ?? item.interaction_spec?.starter_code ?? "").slice(0, 20000) }
            : { external_processing_ack: true, science_tool_authorized: item.item_type === "scientific", text: (draft?.text ?? "").slice(0, 8000) });
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
  const pendingShortAnswer = items.some((item) => item.item_type !== "single_choice" && !attempts[item.id]?.length && (item.item_type === "coding" ? Boolean((drafts[item.id]?.source_code ?? item.interaction_spec?.starter_code ?? "").trim()) : Boolean(drafts[item.id]?.text?.trim())));
  const sourceDegraded = selectedSet?.source_degraded ?? false;
  const historicalSet = Boolean(selectedSet && selectedLesson && selectedSet.lesson_version_id !== selectedLesson.version.id);
  const readOnly = sourceDegraded; // source_degraded is fully read-only for practice

  // Task C: auto-exit coding focus when context changes (item type, set, lesson)
  useEffect(() => {
    if (codeFocused && currentItem && currentItem.item_type !== "coding") setCodeFocused(false);
  }, [codeFocused, currentItem?.item_type]);
  useEffect(() => {
    if (codeFocused) setCodeFocused(false);
  }, [selectedSet?.id, lessonId]);

  // Task D: clear stale scratchRun results when the current item changes.
  // The result belongs to the item that initiated the run; switching items
  // must not show the old item's output.
  useEffect(() => {
    if (scratchRunItemId && currentItem && scratchRunItemId !== currentItem.id) {
      setScratchRun(null);
      setScratchRunItemId(null);
      setScratchRunInputSnapshot(null);
      scratchRunTokenRef.current = null;
      setScratchBusy(false);
    }
  }, [currentItem?.id, scratchRunItemId]);

  // Task D §3: clear stale scratchRun results when the source code or stdin
  // for the current item changes. We compare the current input against the
  // snapshot recorded at run initiation time. If they differ, the result is
  // stale and must be cleared. This effect does NOT depend on scratchRun
  // itself, so it won't clear a result immediately after runCurrentCode
  // writes it.
  // IMPORTANT: currentSourceCode must use the SAME fallback chain as
  // runCurrentCode (draft ?? starter_code ?? ""), otherwise running
  // unedited starter code would produce a snapshot mismatch that
  // immediately clears the result.
  const currentScratchInput = currentItem ? scratchInputs[currentItem.id] : undefined;
  const currentSourceCode = currentItem ? (drafts[currentItem.id]?.source_code ?? currentItem.interaction_spec?.starter_code ?? "") : undefined;
  const currentInputKey = currentItem ? `${currentItem.id}:${currentSourceCode ?? ""}:${currentScratchInput ?? ""}` : null;
  useEffect(() => {
    if (scratchRunItemId && scratchRunInputSnapshot !== null && currentInputKey !== scratchRunInputSnapshot) {
      setScratchRun(null);
      setScratchRunItemId(null);
      setScratchRunInputSnapshot(null);
      scratchRunTokenRef.current = null;
      setScratchBusy(false);
    }
  }, [currentInputKey, scratchRunInputSnapshot, scratchRunItemId]);

  useEffect(() => {
    if (!codeFocused) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setCodeFocused(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [codeFocused]);

  const runCurrentCode = async () => {
    if (!currentItem || currentItem.item_type !== "coding" || !selectedLesson) return;
    const sourceCode = drafts[currentItem.id]?.source_code ?? currentItem.interaction_spec?.starter_code ?? "";
    if (!sourceCode.trim()) return;
    // Task D §3/§4: record the input snapshot at run initiation so we can
    // detect stale results later (user edited source/stdin, or late response
    // from a previous run arrives after the user changed inputs).
    const runItemId = currentItem.id;
    const runInputSnapshot = `${runItemId}:${sourceCode}:${scratchInputs[currentItem.id] ?? ""}`;
    const runToken = crypto.randomUUID();
    scratchRunTokenRef.current = runToken;
    setScratchBusy(true); setError(null); setScratchRun(null); setScratchRunItemId(runItemId); setScratchRunInputSnapshot(runInputSnapshot);
    try {
      const created = await createCodeRun(workspaceId, {
        language: currentItem.interaction_spec?.language ?? "python",
        source_code: wrapPracticeSource(currentItem.interaction_spec?.language ?? "python", sourceCode),
        stdin: scratchInputs[currentItem.id] ?? "",
        course_id: courseId,
        course_version_id: courseVersionId,
        lesson_id: selectedLesson.lesson.id,
        lesson_version_id: selectedLesson.version.id,
      }, crypto.randomUUID());
      let detail = await getCodeRun(workspaceId, created.id);
      // Task D §4: discard late response if a newer run has been initiated
      if (scratchRunTokenRef.current === runToken) setScratchRun(detail);
      const terminal = ["completed", "compile_error", "runtime_error", "timed_out", "output_limited", "failed", "canceled"];
      for (let index = 0; index < 90 && !terminal.includes(detail.status); index += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        detail = await getCodeRun(workspaceId, created.id);
        if (scratchRunTokenRef.current === runToken) setScratchRun(detail);
      }
    } catch (value) {
      if (scratchRunTokenRef.current === runToken) setError(errorMessage(value));
    } finally {
      if (scratchRunTokenRef.current === runToken) setScratchBusy(false);
    }
  };

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
      {genJob.science_verification && genJob.science_verification.status !== "not_used" ? <ScienceVerificationStatus value={genJob.science_verification} /> : null}
      {genJob.error_message ? <small>{genJob.error_code === "coding_item_not_supported_by_lesson" ? "当前课节缺少可执行学习目标或代码证据，无法生成合适的编程题。请选择自动选择或普通题。" : genJob.error_code === "science_item_not_supported_by_lesson" ? "当前课节缺少可计算的数学、物理或化学目标与证据，无法生成合适的科学计算题。请选择自动选择或普通题。" : genJob.error_message}</small> : null}
      {ACTIVE.includes(genJob.status) && genJob.status !== "cancel_requested" ? <button className="secondary-button" disabled={busy} onClick={() => void actJob(() => cancelPracticeJob(workspaceId, genJob.id))} type="button"><Square size={14} />取消</button> : null}
      {["failed", "queue_failed", "canceled"].includes(genJob.status) ? <button className="secondary-button" disabled={busy} onClick={() => void actJob(() => retryPracticeJob(workspaceId, genJob.id))} type="button"><RefreshCw size={14} />重试</button> : null}
    </div> : null}

    {creatingNew || !selectedSet ? <form className="practice-generate" onSubmit={generate}>
      {creatingNew && setId ? <button className="secondary-button practice-return-button" onClick={() => void openSet(setId)} type="button"><ArrowLeft size={15} />返回当前练习</button> : null}
      <p className="muted">为「{reader.course.title} / {selectedLesson?.lesson.title ?? "当前课节"}」生成独立练习。默认 5 题，2 题及以上混合单选与简答。</p>
      <label className="practice-field">题数<input max={10} min={1} onChange={(event) => setItemCount(Number(event.target.value))} type="number" value={itemCount} /></label>
      <label className="practice-field">难度<select onChange={(event) => setDifficulty(event.target.value as PracticeDifficulty)} value={difficulty}><option value="easy">基础</option><option value="standard">标准</option><option value="hard">挑战</option></select></label>
      <label className="practice-field">语言<select onChange={(event) => setOutputLanguage(event.target.value as "lesson" | "zh-CN" | "en")} value={outputLanguage}><option value="lesson">沿用课节语言</option><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
      <label className="practice-field">题型<select onChange={(event) => setItemTypeMode(event.target.value as "auto" | "general_only" | "require_coding" | "require_science")} value={itemTypeMode}><option value="auto">自动选择合适题型</option><option value="general_only">只要普通题</option><option value="require_coding">要求编程题</option><option value="require_science">要求科学计算题</option></select></label>
      {(itemTypeMode === "require_coding" || codeToolAuthorized) ? <div className="code-language-selector"><span>编程语言：</span>{["python", "java", "cpp"].map((lang) => <label key={lang} className={`lang-chip${codeLanguages.includes(lang) ? " selected" : ""}`}><input type="checkbox" checked={codeLanguages.includes(lang)} onChange={() => setCodeLanguages((current) => current.includes(lang) ? current.filter((l) => l !== lang) : [...current, lang])} />{lang === "python" ? "Python" : lang === "java" ? "Java" : "C++"}</label>)}</div> : null}
      {(itemTypeMode === "require_coding" || itemTypeMode === "require_science") ? <small className="practice-mode-hint">材料不适合时将明确失败，不会强行凑题</small> : null}
      {itemTypeMode !== "general_only" ? <div className="practice-tool-authorizations">
        <label className="source-choice"><input checked={codeToolAuthorized} disabled={readOnly} onChange={(event) => setCodeToolAuthorized(event.target.checked)} type="checkbox" />允许使用自托管代码执行工具验证编程题</label>
        <label className="source-choice"><input checked={scienceToolAuthorized} disabled={readOnly} onChange={(event) => setScienceToolAuthorized(event.target.checked)} type="checkbox" />允许将必要的科学计算表达式发送给 Wolfram 验证</label>
      </div> : null}
      <label className="source-choice"><input checked={ack} disabled={readOnly} onChange={(event) => setAck(event.target.checked)} type="checkbox" />我同意将本课节相关资料发送给外部 AI 模型，用于生成练习题</label>
      <button className="primary-button" disabled={busy || !ack || !selectedLesson || readOnly || (itemTypeMode === "require_coding" && (!codeToolAuthorized || codeLanguages.length === 0)) || (itemTypeMode === "require_science" && !scienceToolAuthorized) || Boolean(genJob && ACTIVE.includes(genJob.status))} type="submit">{busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}生成练习</button>
      {readOnly ? <p className="form-error">课程来源已变化：历史题目、作答与反馈仍可查看，但暂不能生成新练习。</p> : null}
    </form> : null}

    {sets.length || selectedSet ? <div className="practice-set-toolbar"><label className="practice-set-picker"><span><ListChecks size={16} />练习记录</span><select aria-label="练习集合" onChange={(event) => { setCreatingNew(false); onSetId(event.target.value); }} value={selectedSet?.id ?? setId}>
      {historicalSet && selectedSet ? <option value={selectedSet.id}>历史课节版本 · {new Date(selectedSet.created_at).toLocaleString("zh-CN")}</option> : null}
      {sets.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.item_count} 题 · {item.difficulty === "easy" ? "基础" : item.difficulty === "hard" ? "挑战" : "标准"}{item.source_degraded ? " · 来源已变化" : ""}</option>)}
    </select></label><button className="secondary-button practice-new-button" disabled={busy || creatingNew} onClick={() => { setCreatingNew(true); setGenJob(null); setAck(false); }} type="button"><Plus size={15} />新建练习</button></div> : null}

    {historicalSet ? <p className="practice-history-notice" role="status">这是旧课节版本的练习，仅供回看当时的题目、作答与反馈；新课节的练习记录不会包含它。</p> : null}

    {!creatingNew && selectedSet && currentItem ? <div className={`practice-focus${codeFocused ? " practice-code-focused" : ""}`}>
      <div className="practice-progress"><strong>第 {currentOrdinal + 1} / {items.length} 题</strong><small>{{ single_choice: "单选", short_answer: "简答", coding: "编程", scientific: "科学计算" }[currentItem.item_type]} · {selectedSet.difficulty === "easy" ? "基础" : selectedSet.difficulty === "hard" ? "挑战" : "标准"} · {selectedSet.output_language === "zh-CN" ? "简体中文" : "English"}</small>
        {selectedSet.source_degraded ? <small className="form-error">来源已变化：题目、作答与反馈只读，引用可能不可用，不能作答或重做。</small> : null}
      </div>
      <div className="practice-stem"><RichLearningText content={currentItem.stem} compact /></div>
      {currentItem.item_type === "single_choice" ? <div className="practice-options">
        {currentItem.options?.map((option) => <label className={`practice-option ${!answersHidden && drafts[currentItem.id]?.option_key === option.option_key ? "selected" : ""}`} key={option.option_key}><input checked={!answersHidden && drafts[currentItem.id]?.option_key === option.option_key} disabled={busy || readOnly || currentSubmitted} onChange={() => setDrafts((current) => ({ ...current, [currentItem.id]: { ...current[currentItem.id], option_key: option.option_key, ack: false } }))} type="radio" name={`opt-${currentItem.id}`} /><RichLearningText content={option.text} compact /></label>)}
      </div> : currentItem.item_type === "coding" ? <div className="practice-code-answer">
        <div className="practice-code-toolbar">
          <div><Terminal size={16} /><strong>{currentItem.interaction_spec?.language === "cpp" ? "C++" : currentItem.interaction_spec?.language === "java" ? "Java" : "Python"}</strong><span>隔离运行 · {currentItem.interaction_spec?.time_limit_seconds ?? 3}s</span></div>
          <button className="icon-button" onClick={() => setCodeFocused((value) => !value)} title={codeFocused ? "退出专注编码" : "专注编码"} type="button">{codeFocused ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>
          {codeFocused ? <button className="secondary-button practice-exit-focus" onClick={() => setCodeFocused(false)} type="button"><Minimize2 size={15} />退出专注</button> : null}
        </div>
        <div className="practice-code-contract">
          <p><strong>输入</strong>{currentItem.interaction_spec?.input_description ?? "标准输入将作为 UTF-8 字符串传给 solve(input_text)"}</p>
          <p><strong>输出</strong>{currentItem.interaction_spec?.output_description ?? "返回用于判题的 UTF-8 文本"}</p>
          {currentItem.interaction_spec?.constraints?.length ? <ul>{currentItem.interaction_spec.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul> : null}
        </div>
        <CodeWorkbench className="practice-code-editor" readOnly={busy || readOnly || currentSubmitted} language={currentItem.interaction_spec?.language ?? "python"} minHeight={codeFocused ? 480 : 300} maxHeight={codeFocused ? 620 : 420} value={answersHidden ? "" : drafts[currentItem.id]?.source_code ?? currentItem.interaction_spec?.starter_code ?? ""} onChange={(value) => setDrafts((current) => ({ ...current, [currentItem.id]: { ...current[currentItem.id], source_code: value, ack: false } }))} />
        <div className="practice-code-console">
          <label className="source-choice code-execution-policy"><input checked={codeExecutionEnabled} disabled={busy || readOnly} onChange={(event) => void changeCodeExecutionPolicy(event.target.checked)} type="checkbox" />允许此工作区将代码发送到自托管隔离执行环境</label>
          <label><span>自测输入 <small>不会作为正式答案提交</small></span><textarea className="stdin-editor" value={scratchInputs[currentItem.id] ?? ""} onChange={(event) => setScratchInputs((current) => ({ ...current, [currentItem.id]: event.target.value }))} placeholder="输入一组用于试运行的数据" rows={3} /></label>
          <div className="practice-code-run-row"><button className="secondary-button" disabled={!codeExecutionEnabled || scratchBusy || busy || readOnly} onClick={() => void runCurrentCode()} type="button">{scratchBusy ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}试运行</button><small>{codeExecutionEnabled ? "正式交卷后还会运行 3-20 个隐藏用例，并由 AI 结合代码与测试摘要讲解。" : "先启用当前工作区的自托管代码执行，才能试运行。"}</small></div>
          {scratchRun && scratchRunItemId === currentItem.id ? <div className={`practice-code-output ${scratchRun.status}`}><header><strong>运行结果</strong><span>{scratchRun.status}</span></header>{scratchRun.compile_output ? <pre>{scratchRun.compile_output}</pre> : null}{scratchRun.stdout ? <pre>{scratchRun.stdout}</pre> : null}{scratchRun.stderr ? <pre className="error-output">{scratchRun.stderr}</pre> : null}</div> : null}
        </div>
        {currentItem.interaction_spec?.public_examples?.length ? <div className="practice-public-cases"><strong>公开示例</strong>{currentItem.interaction_spec.public_examples.map((example, index) => <pre key={index}>输入：{example.input}{"\n"}输出：{example.expected_output}</pre>)}</div> : null}
      </div> : <textarea className="practice-textarea" disabled={busy || readOnly || currentSubmitted} maxLength={8000} onChange={(event) => setDrafts((current) => ({ ...current, [currentItem.id]: { ...current[currentItem.id], text: event.target.value } }))} placeholder={currentItem.item_type === "scientific" ? `写出完整解答过程：公式、推导、代入、单位与最终结论${currentItem.interaction_spec?.unit ? `（目标单位：${currentItem.interaction_spec.unit}）` : ""}` : "输入简答（最多 8000 字符）"} rows={8} value={answersHidden ? "" : drafts[currentItem.id]?.text ?? ""} />}

      <div className={`practice-actions${codeFocused ? " practice-actions-hidden" : ""}`}>
        <button className="icon-button" disabled={currentOrdinal <= 0} onClick={() => setCurrentOrdinal((value) => value - 1)} title="上一题" type="button"><ChevronLeft size={18} /></button>
        <button className="icon-button" disabled={currentOrdinal >= items.length - 1} onClick={() => setCurrentOrdinal((value) => value + 1)} title="下一题" type="button"><ChevronRight size={18} /></button>
        {currentOrdinal === items.length - 1 ? <button className="primary-button" disabled={busy || readOnly || (pendingShortAnswer && !submissionAck)} onClick={() => void submitPaper()} type="button">{busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}交卷</button> : null}
        {hasSubmittedAnswers ? <button className="secondary-button" onClick={() => setAnswersHidden((value) => !value)} type="button">{answersHidden ? <Eye size={15} /> : <EyeOff size={15} />}{answersHidden ? "显示答案" : "遮挡答案"}</button> : null}
        <button className="secondary-button" disabled={busy} onClick={() => void removeSet()} type="button"><Trash2 size={15} />删除集合</button>
      </div>

      {currentOrdinal === items.length - 1 && pendingShortAnswer ? <label className="source-choice submission-consent"><input checked={submissionAck} disabled={readOnly || busy} onChange={(event) => setSubmissionAck(event.target.checked)} type="checkbox" />我同意将本次答卷和必要的评分资料发送给配置的外部模型；科学题需要时会发送最小表达式到 Wolfram</label> : null}

      {latestAttempt && !answersHidden ? <FeedbackView attempt={latestAttempt} workspaceId={workspaceId} citations={currentItem.citations} /> : null}
    </div> : null}

    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </section>;
}

type FeedbackCitation = { citation_key: string; document_name: string; heading_path: string[]; page_start: number | null; page_end: number | null };

function ScienceVerificationStatus({ value }: { value: ScienceVerificationRead }) {
  // Task A: only render for verified/failed states; not_used is filtered at
  // the call site. Labels use Set-level wording ("生成" not "本题").
  const label = value.status === "verified"
    ? "Wolfram 已完成验证"
    : value.status === "failed"
      ? "Wolfram 验证失败"
      : null;
  if (!label) return null;
  const purpose = value.purpose === "reference_answer" ? "参考答案" : "学生最终结果";
  return <div className={`science-verification-status ${value.status}`} role="status"><strong>{label}</strong><span>用途：{purpose}</span>{value.checked_at ? <time dateTime={value.checked_at}>{new Date(value.checked_at).toLocaleString("zh-CN")}</time> : null}</div>;
}

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
    <div className="practice-feedback-head"><strong>{verdictLabel(feedback.verdict)}</strong>{feedback.score != null ? <span>{feedback.score} 分</span> : null}{feedback.coding_tests_total != null ? <small>自动测试评分 · AI 讲解</small> : feedback.is_ai_graded ? <small>AI 反馈</small> : null}</div>
    {feedback.science_verification ? <ScienceVerificationStatus value={feedback.science_verification} /> : null}
    {feedback.coding_tests_total != null ? <div className="coding-feedback-summary"><strong>自动测试：{feedback.coding_tests_passed ?? 0} / {feedback.coding_tests_total} 通过</strong>{feedback.coding_error_categories?.length ? <span>{feedback.coding_error_categories.join(" · ")}</span> : null}</div> : null}
    {feedback.coding_public_cases?.length ? <div className="coding-public-results">{feedback.coding_public_cases.map((result, index) => <span className={result.passed ? "passed" : "failed"} key={index}>公开用例 {index + 1}：{result.passed ? "通过" : "未通过"}</span>)}</div> : null}
    {feedback.criterion_results.length ? <ul className="practice-rubric">{feedback.criterion_results.map((result) => <li key={result.criterion_key}><span>{result.met === "full" ? "✔" : result.met === "partial" ? "◑" : "✘"} {humanizeFeedbackText(result.note, citations)}</span></li>)}</ul> : null}
    {feedback.feedback_blocks.map((block) => <div className={`feedback-block ${block.type}`} key={block.block_key}><RichLearningText content={humanizeFeedbackText(block.text, citations)} compact />{block.citation_ids.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</div>)}
    {feedback.citations.length ? <div className="citation-list">{feedback.citations.map((citation) => <div key={citation.citation_key}><strong>{numbers.get(citation.citation_key)}. {[citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ")}</strong>{!citation.available ? <small>来源已不可用</small> : null}</div>)}</div> : null}
  </div>;
}
