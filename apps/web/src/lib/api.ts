const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface ReadinessCheck {
  ok: boolean;
  detail: string;
}

export interface Readiness {
  status: "ready" | "degraded";
  checks: {
    postgres: ReadinessCheck;
    qdrant: ReadinessCheck;
    redis: ReadinessCheck;
    storage: ReadinessCheck;
  };
}

export interface SystemInfo {
  app_name: string;
  environment: string;
  storage: { configured: boolean };
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  name: string;
  description?: string | null;
}

export interface WorkspaceDeletionImpact {
  document_count: number;
  course_count: number;
  active_job_count: number;
  tutor_session_count: number;
}

export interface WorkspaceDeletionJob {
  id: string;
  workspace_id: string;
  status: "queued" | "queue_failed" | "running" | "retry_wait" | "succeeded" | "failed";
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface IngestionJob {
  id: string;
  workspace_id: string;
  document_version_id: string | null;
  status: "queued" | "queue_failed" | "running" | "retry_wait" | "succeeded" | "failed" | "canceled";
  attempt_count: number;
  error_message: string | null;
  next_attempt_at: string | null;
}

export interface DocumentUpload {
  document: { id: string; display_name: string };
  job: IngestionJob;
}

export interface DocumentSummary {
  id: string;
  display_name: string;
  updated_at: string;
  current_version: { byte_size: number; mime_type: string; processing_status: string } | null;
  latest_job: IngestionJob | null;
}

export interface RetrievalResult {
  score: number;
  text: string;
  citation: { chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number };
}

export interface BatchItem {
  id: string;
  client_ordinal: number;
  display_filename: string;
  declared_byte_size: number;
  status: string;
  error_message: string | null;
}

export interface IngestionBatch {
  id: string;
  status: string;
  item_count: number;
  ready_count: number;
  failed_count: number;
  canceled_count: number;
  items: BatchItem[];
}

export interface AnswerResponse {
  trace_id: string;
  status: "succeeded" | "insufficient_evidence" | "failed";
  claims: { text: string; citation_ids: string[] }[];
  citations: { citation_id: string; chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; text: string }[];
  limitations: string[];
  model: string | null;
}

export interface Course {
  id: string;
  workspace_id: string;
  title: string;
  goal: string;
  audience: string | null;
  current_active_version_id: string | null;
  source_degraded: boolean;
  source_count: number;
  published_lesson_count: number;
  pending_lesson_count: number;
  latest_job: CourseGenerationJob | null;
}

export interface CourseGenerationJob {
  id: string;
  course_id: string;
  course_version_id: string | null;
  lesson_id: string | null;
  job_type: "course_outline" | "lesson_draft";
  output_language: "zh-CN" | "en";
  status: string;
  attempt_count: number;
  error_message: string | null;
}

export interface LessonCitation { citation_id: string; block_key: string; document_id: string; document_version_id: string; chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; page_start: number | null; page_end: number | null; available: boolean }
export interface LessonVersion { id: string; version_number: number; status: string; title: string; learning_objectives: string[]; blocks: { block_key: string; type: string; text: string; citation_ids: string[] }[]; citations?: LessonCitation[] }
export interface CourseLesson { id: string; title: string; objective: string; current_published_version_id: string | null; versions?: LessonVersion[]; published_version?: LessonVersion | null }
export interface CourseVersion { id: string; version_number: number; status: string; title: string; summary: string | null; source_degraded: boolean; sections: { id: string; title: string; objective: string; lessons: CourseLesson[] }[] }
export interface CourseDetail { course: Course; versions: CourseVersion[] }
export interface CourseReader { course: Course; version: CourseVersion }
export interface TutorCitation { citation_id: string; block_key: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; page_start: number | null; page_end: number | null }
export interface TutorTurn { id: string; session_id: string; ordinal: number; attempt_number: number; status: string; question: string; scope: "course" | "lesson"; section_id: string | null; lesson_id: string | null; lesson_version_id: string | null; answer_blocks: { block_key: string; type: string; text: string; citation_ids: string[] }[] | null; citations: TutorCitation[]; error_code: string | null; error_message: string | null; created_at: string; completed_at: string | null }
export interface TutorSession { id: string; workspace_id: string; course_id: string; course_version_id: string; status: string; provider: string; model: string; created_at: string; turns: TutorTurn[] }

export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  return request<Readiness>("/ready", { signal });
}

export async function fetchSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  return request<SystemInfo>("/api/v1/system/info", { signal });
}

export async function fetchWorkspaces(signal?: AbortSignal): Promise<Workspace[]> {
  return request<Workspace[]>("/api/v1/workspaces", { signal });
}

export async function createWorkspace(payload: WorkspaceCreate): Promise<Workspace> {
  return request<Workspace>("/api/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchWorkspaceDeletionImpact(workspaceId: string): Promise<WorkspaceDeletionImpact> {
  return request<WorkspaceDeletionImpact>(`/api/v1/workspaces/${workspaceId}/deletion-impact`);
}

export async function deleteWorkspace(workspaceId: string, confirmationName: string, idempotencyKey: string = crypto.randomUUID()): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/${workspaceId}/deletion`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ confirmation_name: confirmationName })
  });
}

export async function fetchWorkspaceDeletionJob(jobId: string): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/deletion-jobs/${jobId}`);
}

export async function retryWorkspaceDeletion(jobId: string): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/deletion-jobs/${jobId}/retry`, { method: "POST" });
}

export async function uploadDocument(workspaceId: string, file: File): Promise<DocumentUpload> {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentUpload>(`/api/v1/workspaces/${workspaceId}/documents`, { method: "POST", body: form });
}

export async function uploadDocumentBatch(workspaceId: string, files: File[], idempotencyKey: string): Promise<IngestionBatch> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches`, {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: form
  });
}

export async function fetchDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}`);
}

export async function retryDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}/retry`, { method: "POST" });
}

export async function cancelDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}/cancel`, { method: "POST" });
}

export async function fetchDocuments(workspaceId: string, signal?: AbortSignal): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>(`/api/v1/workspaces/${workspaceId}/documents`, { signal });
}

export async function deleteDocument(workspaceId: string, documentId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/documents/${documentId}`, { method: "DELETE" });
}

export async function fetchDocumentCourseImpact(workspaceId: string, documentId: string): Promise<{ affected_course_count: number }> {
  return request(`/api/v1/workspaces/${workspaceId}/documents/${documentId}/course-impact`);
}

export async function retryIngestionJob(workspaceId: string, jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/ingestion-jobs/${jobId}/retry`, { method: "POST" });
}

export async function fetchIngestionJob(workspaceId: string, jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/ingestion-jobs/${jobId}`);
}

export async function searchMaterials(workspaceId: string, query: string): Promise<{ results: RetrievalResult[] }> {
  return request<{ results: RetrievalResult[] }>(`/api/v1/workspaces/${workspaceId}/rag/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 5 })
  });
}

export async function answerMaterials(workspaceId: string, question: string): Promise<AnswerResponse> {
  return request<AnswerResponse>(`/api/v1/workspaces/${workspaceId}/rag/answer`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, top_k: 5 })
  });
}

export async function fetchCourses(workspaceId: string): Promise<Course[]> {
  return request<Course[]>(`/api/v1/workspaces/${workspaceId}/courses`);
}

export async function createCourse(workspaceId: string, payload: { title: string; goal: string; audience?: string; document_ids: string[]; output_language: "zh-CN" | "en" }): Promise<{ course: Course; job: CourseGenerationJob }> {
  return request(`/api/v1/workspaces/${workspaceId}/courses`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ ...payload, external_processing_ack: true }) });
}

export async function fetchCourse(workspaceId: string, courseId: string): Promise<CourseDetail> {
  return request<CourseDetail>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}`);
}

export async function fetchCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}`);
}

export async function fetchCourseJobs(workspaceId: string): Promise<CourseGenerationJob[]> {
  return request<CourseGenerationJob[]>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs`);
}

export async function retryCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}/retry`, { method: "POST" });
}

export async function cancelCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}/cancel`, { method: "POST" });
}

export async function generateLesson(workspaceId: string, courseId: string, versionId: string, lessonId: string, outputLanguage: "zh-CN" | "en"): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${versionId}/lessons/${lessonId}/generations`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ external_processing_ack: true, output_language: outputLanguage }) });
}

export async function publishLesson(workspaceId: string, lessonId: string, versionId: string, expectedCurrentVersionId: string | null): Promise<LessonVersion> {
  return request<LessonVersion>(`/api/v1/workspaces/${workspaceId}/lessons/${lessonId}/versions/${versionId}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_current_published_version_id: expectedCurrentVersionId }) });
}

export async function activateCourse(workspaceId: string, courseId: string, versionId: string, expectedCurrentVersionId: string | null): Promise<CourseVersion> {
  return request<CourseVersion>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${versionId}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_current_active_version_id: expectedCurrentVersionId }) });
}

export async function fetchCourseReader(workspaceId: string, courseId: string): Promise<CourseReader> {
  return request<CourseReader>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/reader`);
}

export async function regenerateCourseOutline(workspaceId: string, courseId: string, documentIds: string[], outputLanguage: "zh-CN" | "en"): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/outline-generations`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ document_ids: documentIds, external_processing_ack: true, output_language: outputLanguage }) });
}

export async function deleteCourse(workspaceId: string, courseId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}`, { method: "DELETE" });
}

export async function fetchTutorSessions(workspaceId: string, courseId: string, versionId: string): Promise<TutorSession[]> {
  return request<TutorSession[]>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/tutor-sessions?course_version_id=${encodeURIComponent(versionId)}`);
}

export async function createTutorSession(workspaceId: string, courseId: string, versionId: string): Promise<TutorSession> {
  return request<TutorSession>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/tutor-sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course_version_id: versionId, external_processing_ack: true }) });
}

export async function fetchTutorSession(workspaceId: string, sessionId: string): Promise<TutorSession> {
  return request<TutorSession>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}`);
}

export async function deleteTutorSession(workspaceId: string, sessionId: string): Promise<void> {
  return request<void>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}`, { method: "DELETE" });
}

export async function createTutorTurn(workspaceId: string, sessionId: string, payload: { question: string; scope: "course" | "lesson"; section_id?: string; lesson_id?: string; lesson_version_id?: string }, idempotencyKey: string = crypto.randomUUID()): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}/turns`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload) });
}

export async function cancelTutorTurn(workspaceId: string, turnId: string): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/cancel`, { method: "POST" });
}

export async function retryTutorTurn(workspaceId: string, turnId: string): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/retry`, { method: "POST" });
}

export function tutorTurnEventsUrl(workspaceId: string, turnId: string): string {
  return `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/events`;
}

interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        message = body.detail[0].msg;
      }
    } catch {
      // Keep the status-based message for non-JSON errors.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
