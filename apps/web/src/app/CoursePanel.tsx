import { ArrowLeft, BookOpen, Check, ChevronLeft, ChevronRight, Expand, LoaderCircle, Play, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  activateCourse, cancelCourseJob, Course, CourseDetail, CourseGenerationJob, CourseReader,
  createCourse, deleteCourse, DocumentSummary, fetchCourse, fetchCourseJob, fetchCourseJobs, fetchCourseReader,
  fetchCourses, generateLesson, LessonCitation, LessonVersion, publishLesson, regenerateCourseOutline, retryCourseJob
} from "../lib/api";
import { TutorPanel } from "./TutorPanel";
import { PracticePanel } from "./PracticePanel";
import { PracticeHistoryPanel } from "./PracticeHistoryPanel";

const errorMessage = (value: unknown) => value instanceof Error ? value.message : String(value);
const activeJob = (status: string) => ["queued", "running", "retry_wait", "cancel_requested"].includes(status);
type FocusState = { mode: "draft"; lessonId: string; versionId: string; courseVersionId: string } | { mode: "reader"; lessonId: string };

const pageLabel = (start: number | null, end: number | null) => start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`;
const citationLocation = (citation: LessonCitation) => {
  const parts = [citation.document_name, ...(citation.heading_path ?? []), pageLabel(citation.page_start, citation.page_end)].filter(Boolean);
  return parts.join(" > ");
};

function CitationList({ version }: { version: LessonVersion }) {
  if (!version.citations?.length) return null;
  const numbers = new Map(version.citations.map((citation, index) => [citation.citation_id, index + 1]));
  return <aside className="citation-list" aria-label="课节引用">
    {version.citations.map((citation) => <div key={citation.citation_id}>
      <strong>{numbers.get(citation.citation_id)}. {citation.available ? citationLocation(citation) : citation.document_name}</strong>
      {!citation.available ? <small>来源已不可用</small> : null}
    </div>)}
  </aside>;
}

function LessonContent({ version, compact = false }: { version: LessonVersion; compact?: boolean }) {
  const numbers = new Map((version.citations ?? []).map((citation, index) => [citation.citation_id, index + 1]));
  return <div className={`lesson-draft-content${compact ? " compact" : ""}`}>
    <div className="draft-heading"><strong>{version.title}</strong><small>草稿版本 {version.version_number}</small></div>
    {version.learning_objectives.length ? <ul>{version.learning_objectives.map((objective) => <li key={objective}>{objective}</li>)}</ul> : null}
    {version.blocks.map((block) => block.type === "heading"
      ? <h5 key={block.block_key}>{block.text}</h5>
      : <p key={block.block_key}>{block.text}{block.citation_ids?.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</p>)}
    <CitationList version={version} />
  </div>;
}

export function CoursePanel({ workspaceId, documents }: { workspaceId: string; documents: DocumentSummary[] }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [detail, setDetail] = useState<CourseDetail | null>(null);
  const [reader, setReader] = useState<CourseReader | null>(null);
  const [jobs, setJobs] = useState<CourseGenerationJob[]>([]);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [outputLanguage, setOutputLanguage] = useState<"zh-CN" | "en">("zh-CN");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLessonVersions, setSelectedLessonVersions] = useState<Record<string, string>>({});
  const [focus, setFocus] = useState<FocusState | null>(null);
  const [middleView, setMiddleView] = useState<"content" | "practice">("content");
  const [rightView, setRightView] = useState<"tutor" | "history">("tutor");
  const [currentLessonId, setCurrentLessonId] = useState("");
  const [practiceSetId, setPracticeSetId] = useState("");
  const mergeJob = useCallback((next: CourseGenerationJob) => {
    setJobs((current) => [next, ...current.filter((item) => item.id !== next.id)].slice(0, 20));
  }, []);
  const jobTarget = (job: CourseGenerationJob) => {
    const course = detail?.course.id === job.course_id ? detail.course : courses.find((item) => item.id === job.course_id);
    const lesson = job.lesson_id && detail?.course.id === job.course_id
      ? detail.versions.flatMap((version) => version.sections.flatMap((section) => section.lessons)).find((item) => item.id === job.lesson_id)
      : null;
    return job.job_type === "lesson_draft"
      ? `课节：${lesson?.title ?? `${course?.title ?? "课程"} / ${job.lesson_id?.slice(0, 8)}`}`
      : `课程大纲：${course?.title ?? "正在读取课程信息"}`;
  };

  const refreshCourses = useCallback(async () => setCourses(await fetchCourses(workspaceId)), [workspaceId]);
  const openCourse = useCallback(async (courseId: string, resetView = true) => {
    setReader(null); setSources([]); setError(null);
    if (resetView) { setFocus(null); setSelectedLessonVersions({}); }
    try { setDetail(await fetchCourse(workspaceId, courseId)); }
    catch (value) { setError(errorMessage(value)); }
  }, [workspaceId]);

  useEffect(() => {
    setDetail(null); setReader(null); setJobs([]); setSources([]); setError(null); setFocus(null); setSelectedLessonVersions({});
    void Promise.all([refreshCourses(), fetchCourseJobs(workspaceId).then(setJobs)]).catch((value) => setError(errorMessage(value)));
  }, [refreshCourses, workspaceId]);

  useEffect(() => {
    if (!focus) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setFocus(null); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [focus]);

  useEffect(() => {
    const activeJobs = jobs.filter((job) => activeJob(job.status));
    if (!activeJobs.length) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const nextJobs = await Promise.all(activeJobs.map((job) => fetchCourseJob(workspaceId, job.id)));
        if (!active) return;
        setJobs((current) => current.map((job) => nextJobs.find((next) => next.id === job.id) ?? job));
        if (nextJobs.some((next) => next.status === "succeeded")) {
          await refreshCourses();
          const selected = nextJobs.find((next) => next.status === "succeeded" && next.course_id === detail?.course.id);
          if (selected) await openCourse(selected.course_id, false);
        }
        if (nextJobs.some((next) => activeJob(next.status))) timer = window.setTimeout(() => void poll(), 1500);
      } catch (value) {
        if (active) setError(errorMessage(value));
      }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [jobs, detail?.course.id, openCourse, refreshCourses, workspaceId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await createCourse(workspaceId, { title, goal, document_ids: sources, output_language: outputLanguage });
      mergeJob(created.job); setTitle(""); setGoal(""); setSources([]);
      await refreshCourses();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const act = async (work: () => Promise<unknown>, courseId: string) => {
    setBusy(true); setError(null);
    try { await work(); await openCourse(courseId, false); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const setJobFrom = async (work: () => Promise<CourseGenerationJob>) => {
    setBusy(true); setError(null);
    try { mergeJob(await work()); } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const startNewCourse = () => {
    setDetail(null); setReader(null); setFocus(null); setSources([]); setTitle(""); setGoal(""); setError(null);
  };

  const focusedDraft = focus?.mode === "draft" && detail
    ? detail.versions.flatMap((courseVersion) => courseVersion.sections.flatMap((section) => section.lessons.map((lesson) => ({ courseVersion, lesson })))).find(({ lesson }) => lesson.id === focus.lessonId)?.lesson.versions?.find((version) => version.id === focus.versionId)
    : null;
  const focusedDraftLesson = focus?.mode === "draft" && detail
    ? detail.versions.flatMap((courseVersion) => courseVersion.sections.flatMap((section) => section.lessons.map((lesson) => ({ courseVersion, lesson })))).find(({ lesson }) => lesson.id === focus.lessonId)
    : null;
  const readableLessons = reader?.version.sections.flatMap((section) => section.lessons).filter((lesson) => lesson.published_version) ?? [];
  const focusedReaderIndex = focus?.mode === "reader" ? readableLessons.findIndex((lesson) => lesson.id === focus.lessonId) : -1;
  const focusedReaderLesson = focusedReaderIndex >= 0 ? readableLessons[focusedReaderIndex] : null;
  const activeCourseJobs = jobs.filter((job) => activeJob(job.status));
  const visibleJobs = activeCourseJobs.length
    ? [...activeCourseJobs, ...jobs.filter((job) => !activeJob(job.status)).slice(0, 1)]
    : jobs.slice(0, 2);

  // Shared practice scope: reset set selection and re-anchor the lesson when the
  // Course/Course Version (or Workspace, which clears the reader) changes, so no
  // stale selector value survives into the new scope.
  useEffect(() => {
    setPracticeSetId("");
    const ids = (reader?.version.sections.flatMap((section) => section.lessons).filter((lesson) => lesson.published_version) ?? []).map((lesson) => lesson.id);
    setCurrentLessonId((current) => (current && ids.includes(current) ? current : ids[0] ?? ""));
    // Intentionally scoped to course/version identity so a scope switch resets
    // practice state without depending on the volatile sections array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reader?.course.id, reader?.version.id]);

  // Left directory click navigates the Reader: scroll to the selected lesson
  // when the content view is active. This gives the shared lesson a real effect
  // on the main content, not just the Practice/Tutor selectors.
  useEffect(() => {
    if (middleView !== "content" || !currentLessonId || !reader) return;
    const el = document.getElementById(`lesson-article-${currentLessonId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [currentLessonId, middleView, reader]);

  return <section className="course-panel">
    <div className="section-heading"><div><span>课程</span><h2>章节化学习</h2></div><BookOpen /></div>
    <div className="course-layout">
      <aside className="course-list">
        <button className="secondary-button new-course-button" onClick={startNewCourse} type="button"><Plus size={16} />新建课程</button>
        {courses.map((course) => <button className={detail?.course.id === course.id ? "course-row active" : "course-row"} key={course.id} onClick={() => void openCourse(course.id)} type="button">
          <strong>{course.title}</strong>
          <small>{course.source_degraded ? "来源已变化" : course.current_active_version_id ? "可阅读" : "准备中"} · {course.source_count} 份来源 · {course.published_lesson_count}/{course.published_lesson_count + course.pending_lesson_count} 已发布</small>
          <small>最新任务：{course.latest_job?.status ?? "无"}</small>
        </button>)}
        {!courses.length ? <p className="muted">暂无课程</p> : null}
      </aside>

      <div className="course-workspace">
        <label className="generation-language">生成语言<select onChange={(event) => setOutputLanguage(event.target.value as "zh-CN" | "en")} value={outputLanguage}><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
        {jobs.length ? <div className="job-queue job-summary-sticky" role="status"><div className="job-queue-heading"><strong>生成任务</strong>{jobs.length > visibleJobs.length ? <small>仅显示最近 {visibleJobs.length} 条</small> : null}</div>{visibleJobs.map((job) => <div className={`job-summary ${job.status === "failed" || job.status === "queue_failed" ? "failed" : ""}`} key={job.id}>
          {activeJob(job.status) ? <LoaderCircle className="spin" size={17} /> : null}
          <p><strong>{jobTarget(job)}</strong><span> · {job.output_language === "zh-CN" ? "简体中文" : "English"} · {job.status} · 第 {job.attempt_count} 次尝试</span>{job.error_message ? ` · ${job.error_message}` : ""}</p>
          {["failed", "queue_failed"].includes(job.status) ? <button className="secondary-button" onClick={() => void setJobFrom(() => retryCourseJob(workspaceId, job.id))} type="button">重试</button> : null}
          {activeJob(job.status) && job.status !== "cancel_requested" ? <button className="secondary-button" onClick={() => void setJobFrom(() => cancelCourseJob(workspaceId, job.id))} type="button">取消</button> : null}
        </div>)}</div> : null}

        {!detail ? <form className="course-create" onSubmit={submit}>
          <label>课程标题<input maxLength={200} onChange={(event) => setTitle(event.target.value)} required value={title} /></label>
          <label>学习目标<textarea maxLength={4000} onChange={(event) => setGoal(event.target.value)} required value={goal} /></label>
          <fieldset><legend>选择 ready 资料（最多 20 份）</legend>{documents.filter((item) => item.current_version?.processing_status === "ready").map((document) => <label className="source-choice" key={document.id}><input checked={sources.includes(document.id)} disabled={!sources.includes(document.id) && sources.length >= 20} onChange={(event) => setSources((current) => event.target.checked ? [...current, document.id] : current.filter((id) => id !== document.id))} type="checkbox" />{document.display_name}</label>)}</fieldset>
          <small>生成时，检索到的所选资料片段会发送给当前配置的 generation provider。</small>
          <button className="primary-button" disabled={busy || !title.trim() || !goal.trim() || !sources.length} type="submit">{busy ? <LoaderCircle className="spin" /> : <Sparkles />}创建并生成大纲</button>
        </form> : <div className="course-detail">
          <header><div><h3>{detail.course.title}</h3><p>{detail.course.goal}</p></div><div className="course-actions">
            <button className="secondary-button" disabled={busy || !sources.length} onClick={() => void setJobFrom(() => regenerateCourseOutline(workspaceId, detail.course.id, sources, outputLanguage))} title="使用下方勾选的资料生成新的大纲版本" type="button"><RefreshCw size={16} />生成新大纲版本</button>
            {detail.course.current_active_version_id ? <button className="secondary-button" onClick={() => void fetchCourseReader(workspaceId, detail.course.id).then(setReader).catch((value) => setError(errorMessage(value)))} type="button"><BookOpen size={16} />阅读</button> : null}
            <button className="icon-button" disabled={busy} onClick={() => void deleteCourse(workspaceId, detail.course.id).then(() => { setDetail(null); setReader(null); return refreshCourses(); }).catch((value) => setError(errorMessage(value)))} title="删除课程" type="button"><Trash2 size={16} /></button>
          </div></header>

          {!reader ? <fieldset className="outline-sources"><legend>新大纲版本所用资料</legend>{documents.filter((item) => item.current_version?.processing_status === "ready").map((document) => <label className="source-choice" key={document.id}><input checked={sources.includes(document.id)} disabled={!sources.includes(document.id) && sources.length >= 20} onChange={(event) => setSources((current) => event.target.checked ? [...current, document.id] : current.filter((id) => id !== document.id))} type="checkbox" />{document.display_name}</label>)}</fieldset> : null}

          {reader ? <div className="reader-with-tutor"><div className="reader"><nav className="reader-directory" aria-label="课节目录">{reader.version.sections.map((section) => <div key={section.id}><strong>{section.title}</strong>{section.lessons.map((lesson) => <button className={lesson.id === currentLessonId && lesson.published_version ? "directory-lesson active" : "directory-lesson"} disabled={!lesson.published_version} key={lesson.id} onClick={() => lesson.published_version && setCurrentLessonId(lesson.id)} type="button">{lesson.title}</button>)}</div>)}</nav><main>
            <div className="reader-view-switch" role="tablist" aria-label="中间视图"><button className={middleView === "content" ? "active" : ""} onClick={() => setMiddleView("content")} role="tab" type="button">正文</button><button className={middleView === "practice" ? "active" : ""} onClick={() => setMiddleView("practice")} role="tab" type="button">练习</button></div>
            <div className={middleView === "practice" ? "reader-content hidden" : "reader-content"}>{reader.version.sections.flatMap((section) => section.lessons).map((lesson) => <article id={`lesson-article-${lesson.id}`} key={lesson.id}><header className="reader-lesson-heading"><h4>{lesson.title}</h4>{lesson.published_version ? <button className="icon-button" onClick={() => setFocus({ mode: "reader", lessonId: lesson.id })} title="专注阅读" type="button"><Expand size={16} /></button> : null}</header>{lesson.published_version ? <LessonContent compact version={lesson.published_version} /> : <p className="muted">尚未发布</p>}</article>)}</div>
            <div className={middleView === "content" ? "reader-practice hidden" : "reader-practice"}><PracticePanel reader={reader} workspaceId={workspaceId} lessonId={currentLessonId} onLessonId={setCurrentLessonId} setId={practiceSetId} onSetId={setPracticeSetId} /></div>
          </main></div><div className="reader-right">
            <div className="reader-view-switch" role="tablist" aria-label="右侧视图"><button className={rightView === "tutor" ? "active" : ""} onClick={() => setRightView("tutor")} role="tab" type="button">Tutor</button><button className={rightView === "history" ? "active" : ""} onClick={() => setRightView("history")} role="tab" type="button">练习记录</button></div>
            <div className={rightView === "history" ? "hidden" : ""}><TutorPanel reader={reader} workspaceId={workspaceId} lessonId={currentLessonId} onLessonId={setCurrentLessonId} /></div>
            <div className={rightView === "tutor" ? "hidden" : ""}><PracticeHistoryPanel reader={reader} workspaceId={workspaceId} lessonId={currentLessonId} setId={practiceSetId} onSetId={setPracticeSetId} /></div>
          </div></div>
            : detail.versions.map((version, versionIndex) => <details className="outline" key={version.id} open={versionIndex === 0}>
              <summary className="outline-header"><strong>版本 {version.version_number} · {version.status}</strong><button className="secondary-button" disabled={busy || version.source_degraded} onClick={(event) => { event.preventDefault(); void act(() => activateCourse(workspaceId, detail.course.id, version.id, detail.course.current_active_version_id), detail.course.id); }} type="button"><Check size={15} />激活</button></summary>
              {version.sections.map((section) => <section key={section.id}><h4>{section.title}</h4><p>{section.objective}</p>{section.lessons.map((lesson) => {
                const versions = [...(lesson.versions ?? [])].sort((left, right) => right.version_number - left.version_number);
                const selected = versions.find((item) => item.id === selectedLessonVersions[lesson.id]) ?? versions[0];
                return <div className="lesson-item" key={lesson.id}><div className="lesson-row"><span><strong>{lesson.title}</strong><small>{lesson.objective}</small></span><div className="lesson-actions">
                  {selected ? <select aria-label={`${lesson.title} 内容版本`} onChange={(event) => setSelectedLessonVersions((current) => ({ ...current, [lesson.id]: event.target.value }))} value={selected.id}>{versions.map((item) => <option key={item.id} value={item.id}>版本 {item.version_number} · {item.status}</option>)}</select> : null}
                  {selected ? <button className="icon-button" onClick={() => setFocus({ mode: "draft", lessonId: lesson.id, versionId: selected.id, courseVersionId: version.id })} title="专注审阅" type="button"><Expand size={16} /></button> : null}
                  {selected?.status === "draft" ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => publishLesson(workspaceId, lesson.id, selected.id, lesson.current_published_version_id), detail.course.id)} type="button"><Check size={15} />发布此版本</button> : null}
                  <button className="secondary-button" disabled={busy || version.source_degraded || jobs.some((job) => job.lesson_id === lesson.id && activeJob(job.status))} onClick={() => void setJobFrom(() => generateLesson(workspaceId, detail.course.id, version.id, lesson.id, outputLanguage))} type="button">{selected ? <RefreshCw size={15} /> : <Play size={15} />}{selected ? "重新生成草稿" : "生成"}</button>
                </div></div>
                  {selected ? <details className="lesson-draft"><summary>预览版本 {selected.version_number}</summary><LessonContent compact version={selected} /></details> : null}
                </div>;
              })}</section>)}
            </details>)}
        </div>}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </div>
    </div>
    {focus?.mode === "draft" && focusedDraft && focusedDraftLesson ? <div className="focus-page" role="dialog" aria-modal="true" aria-label="专注审阅课节草稿"><header><button className="secondary-button" onClick={() => setFocus(null)} type="button"><ArrowLeft size={17} />返回课程</button><div><span>草稿版本 {focusedDraft.version_number} · {focusedDraft.status}</span><h2>{focusedDraftLesson.lesson.title}</h2></div><div className="focus-actions">{focusedDraft.status === "draft" ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => publishLesson(workspaceId, focusedDraftLesson.lesson.id, focusedDraft.id, focusedDraftLesson.lesson.current_published_version_id), detail!.course.id)} type="button"><Check size={16} />发布此版本</button> : null}<button className="primary-button" disabled={busy || focusedDraftLesson.courseVersion.source_degraded || jobs.some((job) => job.lesson_id === focusedDraftLesson.lesson.id && activeJob(job.status))} onClick={() => void setJobFrom(() => generateLesson(workspaceId, detail!.course.id, focusedDraftLesson.courseVersion.id, focusedDraftLesson.lesson.id, outputLanguage))} type="button"><RefreshCw size={16} />重新生成草稿</button></div></header><main><LessonContent version={focusedDraft} /></main></div> : null}
    {focus?.mode === "reader" && focusedReaderLesson?.published_version ? <div className="focus-page" role="dialog" aria-modal="true" aria-label="专注阅读课节"><header><button className="secondary-button" onClick={() => setFocus(null)} type="button"><ArrowLeft size={17} />返回 Reader</button><div><span>已发布版本 {focusedReaderLesson.published_version.version_number}</span><h2>{focusedReaderLesson.title}</h2></div><div className="focus-actions"><button className="icon-button" disabled={focusedReaderIndex <= 0} onClick={() => setFocus({ mode: "reader", lessonId: readableLessons[focusedReaderIndex - 1].id })} title="上一课" type="button"><ChevronLeft size={18} /></button><button className="icon-button" disabled={focusedReaderIndex >= readableLessons.length - 1} onClick={() => setFocus({ mode: "reader", lessonId: readableLessons[focusedReaderIndex + 1].id })} title="下一课" type="button"><ChevronRight size={18} /></button></div></header><main><LessonContent version={focusedReaderLesson.published_version} /></main></div> : null}
  </section>;
}
