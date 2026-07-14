import { BookOpen, Check, LoaderCircle, Play, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  activateCourse, cancelCourseJob, Course, CourseDetail, CourseGenerationJob, CourseReader,
  createCourse, deleteCourse, DocumentSummary, fetchCourse, fetchCourseJob, fetchCourseReader,
  fetchCourses, generateLesson, LessonVersion, publishLesson, regenerateCourseOutline, retryCourseJob
} from "../lib/api";

const errorMessage = (value: unknown) => value instanceof Error ? value.message : String(value);
const activeJob = (status: string) => ["queued", "running", "retry_wait"].includes(status);

function CitationList({ version }: { version: LessonVersion }) {
  if (!version.citations?.length) return null;
  return <aside className="citation-list" aria-label="课节引用">
    {version.citations.map((citation) => <div key={citation.citation_id}>
      <strong>{citation.citation_id} · {citation.document_name}</strong>
      <small>{citation.available ? `${citation.heading_path?.join(" / ") || "文档"} · 字符 ${citation.start_offset}-${citation.end_offset}` : "来源已不可用"}</small>
    </div>)}
  </aside>;
}

function LessonContent({ version }: { version: LessonVersion }) {
  return <div className="lesson-draft-content">
    <div className="draft-heading"><strong>{version.title}</strong><small>草稿版本 {version.version_number}</small></div>
    {version.learning_objectives.length ? <ul>{version.learning_objectives.map((objective) => <li key={objective}>{objective}</li>)}</ul> : null}
    {version.blocks.map((block) => block.type === "heading"
      ? <h5 key={block.block_key}>{block.text}</h5>
      : <p key={block.block_key}>{block.text} <small>{block.citation_ids?.join(" ") ?? ""}</small></p>)}
    <CitationList version={version} />
  </div>;
}

export function CoursePanel({ workspaceId, documents }: { workspaceId: string; documents: DocumentSummary[] }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [detail, setDetail] = useState<CourseDetail | null>(null);
  const [reader, setReader] = useState<CourseReader | null>(null);
  const [job, setJob] = useState<CourseGenerationJob | null>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshCourses = useCallback(async () => setCourses(await fetchCourses(workspaceId)), [workspaceId]);
  const openCourse = useCallback(async (courseId: string) => {
    setReader(null);
    setDetail(await fetchCourse(workspaceId, courseId));
  }, [workspaceId]);

  useEffect(() => {
    setDetail(null); setReader(null); setJob(null); setSources([]); setError(null);
    void refreshCourses();
  }, [refreshCourses]);

  useEffect(() => {
    if (!job || !activeJob(job.status)) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await fetchCourseJob(workspaceId, job.id);
        if (!active) return;
        setJob(next);
        if (next.status === "succeeded") {
          await refreshCourses();
          await openCourse(next.course_id);
        } else if (activeJob(next.status)) {
          timer = window.setTimeout(() => void poll(), 1500);
        }
      } catch (value) {
        if (active) setError(errorMessage(value));
      }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [job, openCourse, refreshCourses, workspaceId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await createCourse(workspaceId, { title, goal, document_ids: sources });
      setJob(created.job); setTitle(""); setGoal(""); setSources([]);
      await refreshCourses();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const act = async (work: () => Promise<unknown>, courseId: string) => {
    setBusy(true); setError(null);
    try { await work(); await openCourse(courseId); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const setJobFrom = async (work: () => Promise<CourseGenerationJob>) => {
    setError(null);
    try { setJob(await work()); } catch (value) { setError(errorMessage(value)); }
  };

  return <section className="course-panel">
    <div className="section-heading"><div><span>课程</span><h2>章节化学习</h2></div><BookOpen /></div>
    <div className="course-layout">
      <aside className="course-list">
        {courses.map((course) => <button className={detail?.course.id === course.id ? "course-row active" : "course-row"} key={course.id} onClick={() => void openCourse(course.id)} type="button">
          <strong>{course.title}</strong>
          <small>{course.source_degraded ? "来源已变化" : course.current_active_version_id ? "可阅读" : "准备中"} · {course.source_count} 份来源 · {course.published_lesson_count}/{course.published_lesson_count + course.pending_lesson_count} 已发布</small>
          <small>最新任务：{course.latest_job?.status ?? "无"}</small>
        </button>)}
        {!courses.length ? <p className="muted">暂无课程</p> : null}
      </aside>

      <div className="course-workspace">
        {job ? <div className={`job-summary job-summary-sticky ${job.status === "failed" || job.status === "queue_failed" ? "failed" : ""}`} role="status">
          {activeJob(job.status) ? <LoaderCircle className="spin" size={17} /> : null}
          <p>生成任务：<strong>{job.status}</strong>{job.error_message ? ` · ${job.error_message}` : ""}</p>
          {["failed", "queue_failed"].includes(job.status) ? <button className="secondary-button" onClick={() => void setJobFrom(() => retryCourseJob(workspaceId, job.id))} type="button">重试</button> : null}
          {activeJob(job.status) ? <button className="secondary-button" onClick={() => void setJobFrom(() => cancelCourseJob(workspaceId, job.id))} type="button">取消</button> : null}
        </div> : null}

        {!detail ? <form className="course-create" onSubmit={submit}>
          <label>课程标题<input maxLength={200} onChange={(event) => setTitle(event.target.value)} required value={title} /></label>
          <label>学习目标<textarea maxLength={4000} onChange={(event) => setGoal(event.target.value)} required value={goal} /></label>
          <fieldset><legend>选择 ready 资料（最多 20 份）</legend>{documents.filter((item) => item.current_version?.processing_status === "ready").map((document) => <label className="source-choice" key={document.id}><input checked={sources.includes(document.id)} disabled={!sources.includes(document.id) && sources.length >= 20} onChange={(event) => setSources((current) => event.target.checked ? [...current, document.id] : current.filter((id) => id !== document.id))} type="checkbox" />{document.display_name}</label>)}</fieldset>
          <small>生成时，检索到的所选资料片段会发送给当前配置的 generation provider。</small>
          <button className="primary-button" disabled={busy || !title.trim() || !goal.trim() || !sources.length} type="submit">{busy ? <LoaderCircle className="spin" /> : <Sparkles />}创建并生成大纲</button>
        </form> : <div className="course-detail">
          <header><div><h3>{detail.course.title}</h3><p>{detail.course.goal}</p></div><div className="course-actions">
            <button className="secondary-button" disabled={busy || !sources.length} onClick={() => void setJobFrom(() => regenerateCourseOutline(workspaceId, detail.course.id, sources))} title="使用下方勾选的资料重新生成大纲" type="button"><RefreshCw size={16} />重新生成</button>
            {detail.course.current_active_version_id ? <button className="secondary-button" onClick={() => void fetchCourseReader(workspaceId, detail.course.id).then(setReader).catch((value) => setError(errorMessage(value)))} type="button"><BookOpen size={16} />阅读</button> : null}
            <button className="icon-button" disabled={busy} onClick={() => void deleteCourse(workspaceId, detail.course.id).then(() => { setDetail(null); setReader(null); return refreshCourses(); }).catch((value) => setError(errorMessage(value)))} title="删除课程" type="button"><Trash2 size={16} /></button>
          </div></header>

          {!reader ? <fieldset className="outline-sources"><legend>重新生成所用资料</legend>{documents.filter((item) => item.current_version?.processing_status === "ready").map((document) => <label className="source-choice" key={document.id}><input checked={sources.includes(document.id)} disabled={!sources.includes(document.id) && sources.length >= 20} onChange={(event) => setSources((current) => event.target.checked ? [...current, document.id] : current.filter((id) => id !== document.id))} type="checkbox" />{document.display_name}</label>)}</fieldset> : null}

          {reader ? <div className="reader"><nav>{reader.version.sections.map((section) => <span key={section.id}>{section.title}</span>)}</nav><main>{reader.version.sections.flatMap((section) => section.lessons).map((lesson) => <article key={lesson.id}><h4>{lesson.title}</h4>{lesson.published_version ? <LessonContent version={lesson.published_version} /> : <p className="muted">尚未发布</p>}</article>)}</main></div>
            : detail.versions.map((version, versionIndex) => <details className="outline" key={version.id} open={versionIndex === 0}>
              <summary className="outline-header"><strong>版本 {version.version_number} · {version.status}</strong><button className="secondary-button" disabled={busy || version.source_degraded} onClick={(event) => { event.preventDefault(); void act(() => activateCourse(workspaceId, detail.course.id, version.id, detail.course.current_active_version_id), detail.course.id); }} type="button"><Check size={15} />激活</button></summary>
              {version.sections.map((section) => <section key={section.id}><h4>{section.title}</h4><p>{section.objective}</p>{section.lessons.map((lesson) => {
                const draft = lesson.versions?.find((item) => item.status === "draft");
                return <div className="lesson-item" key={lesson.id}><div className="lesson-row"><span><strong>{lesson.title}</strong><small>{lesson.objective}</small></span>{draft
                  ? <button className="secondary-button" disabled={busy} onClick={() => void act(() => publishLesson(workspaceId, lesson.id, draft.id, lesson.current_published_version_id), detail.course.id)} type="button"><Check size={15} />发布</button>
                  : <button className="secondary-button" disabled={busy || version.source_degraded} onClick={() => void setJobFrom(() => generateLesson(workspaceId, detail.course.id, version.id, lesson.id))} type="button"><Play size={15} />生成</button>}</div>
                  {draft ? <details className="lesson-draft"><summary>查看生成草稿与引用</summary><LessonContent version={draft} /></details> : null}
                </div>;
              })}</section>)}
            </details>)}
        </div>}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </div>
    </div>
  </section>;
}
