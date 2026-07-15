import {
  Activity,
  BookOpenCheck,
  BotMessageSquare,
  CheckCircle2,
  Database,
  Trash2,
  FileStack,
  FolderOpen,
  FolderPlus,
  HardDrive,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Server,
  TriangleAlert,
  Upload,
  X
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  answerMaterials,
  cancelDocumentBatch,
  createWorkspace,
  deleteDocument,
  deleteWorkspace,
  fetchDocumentBatch,
  DocumentSummary,
  fetchDocuments,
  fetchDocumentCourseImpact,
  fetchIngestionJob,
  fetchReadiness,
  fetchSystemInfo,
  fetchWorkspaces,
  fetchWorkspaceDeletionImpact,
  fetchWorkspaceDeletionJob,
  IngestionJob,
  IngestionBatch,
  Readiness,
  RetrievalResult,
  retryIngestionJob,
  retryDocumentBatch,
  retryWorkspaceDeletion,
  searchMaterials,
  SystemInfo,
  uploadDocumentBatch,
  Workspace,
  WorkspaceDeletionImpact,
  WorkspaceDeletionJob
} from "../lib/api";
import { CoursePanel } from "./CoursePanel";

type LoadState = "idle" | "loading" | "ready" | "error";

const emptyReadiness: Readiness = {
  status: "degraded",
  checks: {
    postgres: { ok: false, detail: "未检查" },
    qdrant: { ok: false, detail: "未检查" },
    redis: { ok: false, detail: "未检查" },
    storage: { ok: false, detail: "未检查" }
  }
};

export function App() {
  const [readiness, setReadiness] = useState<Readiness>(emptyReadiness);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [formState, setFormState] = useState<LoadState>("idle");
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [materialBatch, setMaterialBatch] = useState<IngestionBatch | null>(null);
  const [materialJob, setMaterialJob] = useState<IngestionJob | null>(null);
  const [materialName, setMaterialName] = useState<string | null>(null);
  const [materialError, setMaterialError] = useState<string | null>(null);
  const [materialOperationCount, setMaterialOperationCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RetrievalResult[]>([]);
  const [answer, setAnswer] = useState<Awaited<ReturnType<typeof answerMaterials>> | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null);
  const [deleteImpact, setDeleteImpact] = useState<WorkspaceDeletionImpact | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteState, setDeleteState] = useState<LoadState>("idle");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletionJob, setDeletionJob] = useState<WorkspaceDeletionJob | null>(null);
  const documentsRequest = useRef(0);
  const activeWorkspaceId = useRef<string | null>(null);
  const workspaceDeletionKey = useRef<string | null>(null);

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedId) ?? null,
    [selectedId, workspaces]
  );
  const materialBusy = materialOperationCount > 0;
  const beginMaterialOperation = () => setMaterialOperationCount((count) => count + 1);
  const finishMaterialOperation = () => setMaterialOperationCount((count) => Math.max(0, count - 1));
  const addSelectedFiles = (files: File[]) => {
    setSelectedFiles((current) => {
      const next = new Map(current.map((file) => [fileSelectionKey(file), file]));
      files.forEach((file) => next.set(fileSelectionKey(file), file));
      return [...next.values()];
    });
    setMaterialError(null);
  };
  const removeSelectedFile = (file: File) => {
    const key = fileSelectionKey(file);
    setSelectedFiles((current) => current.filter((candidate) => fileSelectionKey(candidate) !== key));
    setMaterialError(null);
  };
  const clearSearchAndAnswer = () => {
    setSearchQuery("");
    setSearchResults([]);
    setAnswer(null);
  };

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const [nextReadiness, nextSystemInfo, nextWorkspaces] = await Promise.all([
        fetchReadiness(signal),
        fetchSystemInfo(signal),
        fetchWorkspaces(signal)
      ]);
      setReadiness(nextReadiness);
      setSystemInfo(nextSystemInfo);
      setWorkspaces(nextWorkspaces);
      setSelectedId((current) => {
        if (current && nextWorkspaces.some((workspace) => workspace.id === current)) {
          return current;
        }
        return nextWorkspaces[0]?.id ?? null;
      });
      setLoadState("ready");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setLoadState("error");
      setLoadError(error instanceof Error ? error.message : "无法加载平台状态");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    activeWorkspaceId.current = selectedWorkspace?.id ?? null;
  }, [selectedWorkspace?.id]);

  const refreshDocuments = useCallback(async (signal?: AbortSignal) => {
    if (!selectedWorkspace) return;
    const request = ++documentsRequest.current;
    try {
      const nextDocuments = await fetchDocuments(selectedWorkspace.id, signal);
      if (request === documentsRequest.current) setDocuments(nextDocuments);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (request === documentsRequest.current) setDocuments([]);
    }
  }, [selectedWorkspace]);

  useEffect(() => {
    const controller = new AbortController();
    documentsRequest.current += 1;
    setDocuments([]);
    setMaterialJob(null);
    setMaterialName(null);
    setMaterialError(null);
    setSearchResults([]);
    setAnswer(null);
    setMaterialBatch(null);
    setSelectedFiles([]);
    void refreshDocuments(controller.signal);
    return () => controller.abort();
  }, [refreshDocuments]);

  useEffect(() => {
    if (!deletionJob || !["queued", "running", "retry_wait"].includes(deletionJob.status)) return;
    const timer = window.setInterval(() => {
      void fetchWorkspaceDeletionJob(deletionJob.id).then(setDeletionJob).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [deletionJob]);

  useEffect(() => {
    if (!selectedWorkspace || !materialJob || !["queued", "running", "retry_wait"].includes(materialJob.status)) return;
    const timer = window.setInterval(() => {
      void fetchIngestionJob(selectedWorkspace.id, materialJob.id)
        .then((job) => {
          setMaterialJob(job);
        })
        .catch((error) => setMaterialError(error instanceof Error ? error.message : "任务状态更新失败"));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [materialJob, selectedWorkspace]);

  useEffect(() => {
    if (!selectedWorkspace || !materialBatch || ["completed", "partial_failed", "failed", "canceled"].includes(materialBatch.status)) return;
    const timer = window.setInterval(() => {
      void fetchDocumentBatch(selectedWorkspace.id, materialBatch.id)
        .then(setMaterialBatch)
        .catch((error) => setMaterialError(error instanceof Error ? error.message : "批量状态更新失败"));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [materialBatch, selectedWorkspace]);

  useEffect(() => {
    const hasActiveJob = documents.some((document) =>
      document.latest_job && ["queued", "running", "retry_wait"].includes(document.latest_job.status)
    );
    if (!hasActiveJob) return;
    const timer = window.setInterval(() => void refreshDocuments(), 2000);
    return () => window.clearInterval(timer);
  }, [documents, refreshDocuments]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setFormError("请输入 workspace 名称");
      return;
    }
    if (normalizedName.length > 120) {
      setFormError("名称不能超过 120 个字符");
      return;
    }

    setFormState("loading");
    setFormError(null);
    try {
      const workspace = await createWorkspace({
        name: normalizedName,
        description: description.trim() || null
      });
      setWorkspaces((current) => [workspace, ...current]);
      setSelectedId(workspace.id);
      setName("");
      setDescription("");
      setFormState("ready");
    } catch (error) {
      setFormState("error");
      setFormError(error instanceof Error ? error.message : "创建失败");
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace || selectedFiles.length === 0) return;
    const workspaceId = selectedWorkspace.id;
    if (selectedFiles.length > 20 || selectedFiles.some((file) => file.size > 25 * 1024 * 1024) || selectedFiles.reduce((total, file) => total + file.size, 0) > 100 * 1024 * 1024) {
      setMaterialError("单文件最多 25 MiB；单批最多 20 个文件且合计不超过 100 MiB");
      return;
    }
    beginMaterialOperation();
    setMaterialError(null);
    try {
      const key = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
      const result = await uploadDocumentBatch(workspaceId, selectedFiles, key);
      if (activeWorkspaceId.current !== workspaceId) return;
      setMaterialBatch(result);
      setMaterialName(selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} 份资料`);
      void refreshDocuments();
      setSelectedFiles([]);
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "上传失败");
    } finally {
      finishMaterialOperation();
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace || !searchQuery.trim()) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    setSearchResults([]);
    setAnswer(null);
    try {
      const response = await searchMaterials(workspaceId, searchQuery.trim());
      if (activeWorkspaceId.current === workspaceId) setSearchResults(response.results);
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "检索失败");
    } finally {
      finishMaterialOperation();
    }
  }

  async function handleAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace || !searchQuery.trim()) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    setAnswer(null);
    try {
      const response = await answerMaterials(workspaceId, searchQuery.trim());
      if (activeWorkspaceId.current === workspaceId) setAnswer(response);
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "回答失败");
    } finally {
      finishMaterialOperation();
    }
  }

  async function handleBatchRetry() {
    if (!selectedWorkspace || !materialBatch) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    try { const batch = await retryDocumentBatch(workspaceId, materialBatch.id); if (activeWorkspaceId.current === workspaceId) setMaterialBatch(batch); } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "批量重试失败");
    } finally { finishMaterialOperation(); }
  }

  async function handleBatchCancel() {
    if (!selectedWorkspace || !materialBatch || !window.confirm("取消尚未完成的资料处理？已成功资料会保留。")) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    try { const batch = await cancelDocumentBatch(workspaceId, materialBatch.id); if (activeWorkspaceId.current === workspaceId) setMaterialBatch(batch); } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "取消批次失败");
    } finally { finishMaterialOperation(); }
  }

  async function handleRetry() {
    if (!selectedWorkspace || !materialJob) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    try {
      const job = await retryIngestionJob(workspaceId, materialJob.id);
      if (activeWorkspaceId.current !== workspaceId) return;
      setMaterialJob(job);
      await refreshDocuments();
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "重试失败");
    } finally {
      finishMaterialOperation();
    }
  }

  async function handleDocumentRetry(document: DocumentSummary) {
    if (!selectedWorkspace || !document.latest_job) return;
    const workspaceId = selectedWorkspace.id;
    beginMaterialOperation();
    setMaterialError(null);
    try {
      const job = await retryIngestionJob(workspaceId, document.latest_job.id);
      if (activeWorkspaceId.current !== workspaceId) return;
      setMaterialName(document.display_name);
      setMaterialJob(job);
      await refreshDocuments();
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "重试失败");
    } finally {
      finishMaterialOperation();
    }
  }

  async function handleDelete(document: DocumentSummary) {
    if (!selectedWorkspace) return;
    beginMaterialOperation();
    try {
      const impact = await fetchDocumentCourseImpact(selectedWorkspace.id, document.id);
      const impactText = impact.affected_course_count ? `\n${impact.affected_course_count} 门课程将保留，但来源会标记为不可用并停止新的生成、发布和激活。` : "";
      if (!window.confirm(`删除“${document.display_name}”？${impactText}`)) return;
      await deleteDocument(selectedWorkspace.id, document.id); await refreshDocuments();
    } catch (error) {
      setMaterialError(error instanceof Error ? error.message : "删除失败");
    } finally { finishMaterialOperation(); }
  }

  async function openWorkspaceDelete() {
    if (!selectedWorkspace) return;
    setDeleteTarget(selectedWorkspace);
    setDeleteImpact(null);
    setDeleteConfirmation("");
    setDeleteError(null);
    setDeleteState("loading");
    workspaceDeletionKey.current = crypto.randomUUID();
    try {
      setDeleteImpact(await fetchWorkspaceDeletionImpact(selectedWorkspace.id));
      setDeleteState("ready");
    } catch (error) {
      setDeleteState("error");
      setDeleteError(error instanceof Error ? error.message : "无法读取删除影响");
    }
  }

  async function handleWorkspaceDelete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!deleteTarget || deleteConfirmation !== deleteTarget.name) return;
    setDeleteState("loading");
    setDeleteError(null);
    try {
      const job = await deleteWorkspace(deleteTarget.id, deleteConfirmation, workspaceDeletionKey.current ?? crypto.randomUUID());
      setDeletionJob(job);
      setDeleteTarget(null);
      workspaceDeletionKey.current = null;
      setWorkspaces((current) => current.filter((workspace) => workspace.id !== job.workspace_id));
      setSelectedId((current) => current === job.workspace_id ? null : current);
      await refresh();
    } catch (error) {
      setDeleteState("error");
      setDeleteError(error instanceof Error ? error.message : "删除 Workspace 失败");
    }
  }

  async function handleWorkspaceDeleteRetry() {
    if (!deletionJob) return;
    try {
      setDeletionJob(await retryWorkspaceDeletion(deletionJob.id));
    } catch (error) {
      setDeletionJob({ ...deletionJob, error_message: error instanceof Error ? error.message : "重试失败" });
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <BookOpenCheck size={22} />
          </div>
          <div>
            <strong>HelloAgents Learn</strong>
            <span>学习工作台</span>
          </div>
        </div>

        <div className="sidebar-heading">
          <span>Workspaces</span>
          <span className="count">{workspaces.length}</span>
        </div>
        <nav className="workspace-nav" aria-label="Workspace 列表">
          {workspaces.length === 0 ? (
            <div className="nav-empty">
              <FolderOpen size={18} />
              <span>暂无 workspace</span>
            </div>
          ) : (
            workspaces.map((workspace) => (
              <button
                className={workspace.id === selectedId ? "workspace-link active" : "workspace-link"}
                key={workspace.id}
                onClick={() => setSelectedId(workspace.id)}
                type="button"
              >
                <FolderOpen size={17} />
                <span>
                  <strong>{workspace.name}</strong>
                  <small>{workspace.slug}</small>
                </span>
              </button>
            ))
          )}
        </nav>

        <div className="sidebar-footer">
          <span className={readiness.status === "ready" ? "dot ready" : "dot"} />
          <span>{readiness.status === "ready" ? "所有服务就绪" : "部分服务降级"}</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <span className="eyebrow">{systemInfo?.environment ?? "development"}</span>
            <h1>{selectedWorkspace?.name ?? "平台工作台"}</h1>
            <p>{selectedWorkspace?.description ?? "建立学习资料、任务与进度的统一归属。"}</p>
            <select aria-label="切换 Workspace" className="mobile-workspace-select" onChange={(event) => setSelectedId(event.target.value || null)} value={selectedId ?? ""}>
              <option value="">选择 Workspace</option>
              {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
            </select>
          </div>
          <button
            aria-label="刷新平台状态"
            className="icon-button"
            disabled={loadState === "loading"}
            onClick={() => void refresh()}
            title="刷新平台状态"
            type="button"
          >
            {loadState === "loading" ? <LoaderCircle className="spin" /> : <RefreshCw />}
          </button>
        </header>

        {loadError ? (
          <div className="notice error" role="alert">
            <TriangleAlert size={18} />
            <span>{loadError}</span>
          </div>
        ) : null}

        {deletionJob ? (
          <div className={deletionJob.status === "failed" || deletionJob.status === "queue_failed" ? "notice error" : "notice deletion-notice"} role="status">
            {deletionJob.status === "succeeded" ? <CheckCircle2 size={18} /> : deletionJob.status === "failed" || deletionJob.status === "queue_failed" ? <TriangleAlert size={18} /> : <LoaderCircle className="spin" size={18} />}
            <span>Workspace 删除任务：{formatStatus(deletionJob.status)}{deletionJob.error_message ? ` · ${deletionJob.error_message}` : ""}</span>
            {deletionJob.status === "failed" || deletionJob.status === "queue_failed" ? <button className="secondary-button" onClick={() => void handleWorkspaceDeleteRetry()} type="button"><RefreshCw size={15} />重试</button> : null}
          </div>
        ) : null}

        <section className="status-band" aria-label="系统状态">
          <StatusItem icon={<Server />} label="API" ok={loadState !== "error"} detail={loadState === "error" ? "不可用" : "已连接"} />
          <StatusItem icon={<Database />} label="Postgres" {...readiness.checks.postgres} />
          <StatusItem icon={<Activity />} label="Qdrant" {...readiness.checks.qdrant} />
          <StatusItem icon={<Server />} label="Redis" {...readiness.checks.redis} />
          <StatusItem icon={<HardDrive />} label="Storage" {...readiness.checks.storage} />
        </section>

        <div className="workspace-grid">
          <section className="workspace-section" aria-labelledby="workspace-title">
            <div className="section-heading">
              <div>
                <span className="eyebrow">当前空间</span>
                <h2 id="workspace-title">{selectedWorkspace?.name ?? "尚未创建 workspace"}</h2>
              </div>
              <div className="section-heading-actions">
                {selectedWorkspace ? <button aria-label="删除当前 Workspace" className="icon-button danger-icon" onClick={() => void openWorkspaceDelete()} title="删除 Workspace" type="button"><Trash2 /></button> : null}
                <FileStack size={21} />
              </div>
            </div>

            {selectedWorkspace ? (
              <div className="workspace-detail">
                <dl>
                  <div><dt>Slug</dt><dd>{selectedWorkspace.slug}</dd></div>
                  <div><dt>创建时间</dt><dd>{formatDate(selectedWorkspace.created_at)}</dd></div>
                  <div><dt>资料</dt><dd>{documents.length}</dd></div>
                </dl>
                <div className="material-tools">
                  <div className="document-list">
                    {documents.map((document) => {
                      const jobStatus = document.latest_job?.status;
                      const retryable = jobStatus === "failed" || jobStatus === "queue_failed";
                      return <div className="document-row" key={document.id}>
                        <span className="document-identity">
                          <strong>{document.display_name}</strong>
                          <small>{formatDocumentMeta(document)}</small>
                          {document.latest_job?.error_message ? <small className="document-error">{document.latest_job.error_message}</small> : null}
                        </span>
                        <span className={`document-status status-${jobStatus ?? document.current_version?.processing_status ?? "queued"}`}>{formatStatus(jobStatus ?? document.current_version?.processing_status ?? "queued")}</span>
                        <span className="document-actions">
                          {retryable ? <button className="icon-button" disabled={materialBusy} onClick={() => void handleDocumentRetry(document)} title="重试处理" type="button"><RefreshCw /></button> : null}
                          <button className="icon-button" disabled={materialBusy} onClick={() => void handleDelete(document)} title="删除资料" type="button"><Trash2 /></button>
                        </span>
                      </div>;
                    })}
                  </div>
                  <form className="material-form" onSubmit={handleUpload}>
                    <label htmlFor="material-file">批量上传资料</label>
                    <div className="material-action-row">
                      <input accept=".pdf,.md,.txt" id="material-file" multiple name="materialFiles" onChange={(event) => {
                        addSelectedFiles(Array.from(event.target.files ?? []));
                        event.currentTarget.value = "";
                      }} type="file" />
                      <button className="primary-button" disabled={selectedFiles.length === 0 || materialBusy} type="submit"><Upload size={17} /><span>上传</span></button>
                    </div>
                    {selectedFiles.length ? <div className="upload-candidates">
                      <small aria-live="polite">待上传 {selectedFiles.length} 个文件，合计 {formatBytes(selectedFiles.reduce((total, file) => total + file.size, 0))}</small>
                      <ul>
                        {selectedFiles.map((file) => <li key={fileSelectionKey(file)}>
                          <span><strong>{file.name}</strong><small>{formatCandidateFile(file)}</small></span>
                          <button aria-label={`移除 ${file.name}`} className="icon-button" disabled={materialBusy} onClick={() => removeSelectedFile(file)} title="移除待上传文件" type="button"><X /></button>
                        </li>)}
                      </ul>
                    </div> : null}
                  </form>
                  {materialBatch ? <div className="batch-summary">
                    <strong>本批资料：{formatStatus(materialBatch.status)}</strong>
                    <small>已就绪 {materialBatch.ready_count} · 失败 {materialBatch.failed_count} · 已取消 {materialBatch.canceled_count}</small>
                    {materialBatch.items.map((item) => <small key={item.id}>{item.display_filename}：{formatStatus(item.status)}{item.error_message ? ` · ${item.error_message}` : ""}</small>)}
                    {materialBatch.status !== "canceled" && materialBatch.status !== "completed" ? <span className="batch-actions"><button className="secondary-button" disabled={materialBusy} onClick={() => void handleBatchRetry()} type="button">重试失败项</button><button className="secondary-button" disabled={materialBusy} onClick={() => void handleBatchCancel()} type="button">取消未完成项</button></span> : null}
                  </div> : null}
                  <form className="material-form" onSubmit={handleSearch}>
                    <label htmlFor="material-query">检索片段或提出问题</label>
                    <div className="material-action-row"><input id="material-query" name="materialQuery" onChange={(event) => setSearchQuery(event.target.value)} placeholder="输入问题或关键词" value={searchQuery} /><button aria-label="清除检索与回答" className="icon-button" disabled={(!searchQuery && searchResults.length === 0 && !answer) || materialBusy} onClick={clearSearchAndAnswer} title="清除检索与回答" type="button"><X /></button><button className="icon-button" disabled={!searchQuery.trim() || materialBusy} title="检索资料" type="submit"><Search /></button></div>
                  </form>
                  <form className="material-form" onSubmit={handleAnswer}>
                    <button className="secondary-button" disabled={!searchQuery.trim() || materialBusy} type="submit"><BotMessageSquare size={16} /><span>生成带引用回答</span></button>
                  </form>
                  {materialError ? <p className="form-error" role="alert">{materialError}</p> : null}
                  {materialJob ? <p className={materialJob.status === "failed" || materialJob.status === "queue_failed" ? "job-state failed" : "job-state"}>{materialName}：{materialJob.status === "succeeded" ? "处理完成" : materialJob.status === "failed" || materialJob.status === "queue_failed" ? materialJob.error_message ?? "处理失败" : "已进入处理队列"}</p> : null}
                  {materialJob && (materialJob.status === "failed" || materialJob.status === "queue_failed") ? <button className="secondary-button" disabled={materialBusy} onClick={() => void handleRetry()} type="button"><RefreshCw size={16} /><span>重试处理</span></button> : null}
                  {searchResults.map((result) => <article className="search-result" key={result.citation.chunk_id}><p>{result.text}</p><small>{result.citation.document_name}{result.citation.heading_path.length ? ` · ${result.citation.heading_path.join(" / ")}` : ""} · 字符 {result.citation.start_offset}-{result.citation.end_offset}</small></article>)}
                  {answer ? <div className="answer-result">
                    <strong>{answer.status === "insufficient_evidence" ? "资料不足" : "带引用回答"}</strong>
                    {answer.claims.map((claim, index) => <p key={`${answer.trace_id}-${index}`}>{claim.text}<small> [{claim.citation_ids.join(", ")}]</small></p>)}
                    {answer.limitations.map((item) => <small key={item}>{item}</small>)}
                    {answer.citations.map((citation) => <article className="search-result" key={citation.citation_id}><small>{citation.citation_id} · {citation.document_name}{citation.heading_path.length ? ` · ${citation.heading_path.join(" / ")}` : ""}</small><p>{citation.text}</p></article>)}
                  </div> : null}
                </div>
              </div>
            ) : (
              <div className="material-empty large">
                <div className="empty-icon"><FolderOpen size={24} /></div>
                <div>
                  <strong>先创建一个 workspace</strong>
                  <p>它将成为资料与学习状态的业务归属根。</p>
                </div>
              </div>
            )}
          </section>

          <section className="create-section" aria-labelledby="create-title">
            <div className="section-heading">
              <div>
                <span className="eyebrow">新建</span>
                <h2 id="create-title">创建 Workspace</h2>
              </div>
              <FolderPlus size={21} />
            </div>
            <form onSubmit={handleSubmit}>
              <label>
                名称
                <input
                  id="workspace-name"
                  maxLength={120}
                  name="workspaceName"
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：算法复习"
                  value={name}
                />
              </label>
              <label>
                描述
                <textarea
                  id="workspace-description"
                  maxLength={2000}
                  name="workspaceDescription"
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="可选"
                  rows={4}
                  value={description}
                />
              </label>
              {formError ? <p className="form-error" role="alert">{formError}</p> : null}
              <button className="primary-button" disabled={formState === "loading"} type="submit">
                {formState === "loading" ? <LoaderCircle className="spin" size={18} /> : <Plus size={18} />}
                <span>{formState === "loading" ? "正在创建" : "创建 Workspace"}</span>
              </button>
            </form>
          </section>
        </div>
        {selectedWorkspace ? <CoursePanel documents={documents} workspaceId={selectedWorkspace.id} /> : null}
      </main>
      {deleteTarget ? (
        <div className="modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && deleteState !== "loading") setDeleteTarget(null); }}>
          <section aria-labelledby="delete-workspace-title" aria-modal="true" className="confirm-dialog" role="dialog">
            <header>
              <div><span className="eyebrow">不可撤销</span><h2 id="delete-workspace-title">删除 Workspace</h2></div>
              <button aria-label="关闭" className="icon-button" disabled={deleteState === "loading"} onClick={() => setDeleteTarget(null)} title="关闭" type="button"><X /></button>
            </header>
            <p>删除后将立即隐藏并停止写入，后台会清理关联资源。备份不在此次删除范围内。</p>
            {deleteImpact ? <dl className="impact-grid"><div><dt>资料</dt><dd>{deleteImpact.document_count}</dd></div><div><dt>课程</dt><dd>{deleteImpact.course_count}</dd></div><div><dt>运行中任务</dt><dd>{deleteImpact.active_job_count}</dd></div><div><dt>Tutor 会话</dt><dd>{deleteImpact.tutor_session_count}</dd></div></dl> : null}
            {deleteState === "loading" && !deleteImpact ? <p className="dialog-loading"><LoaderCircle className="spin" size={17} />正在读取影响范围</p> : null}
            <form onSubmit={handleWorkspaceDelete}>
              <label htmlFor="delete-workspace-confirmation">输入 <strong>{deleteTarget.name}</strong> 确认删除</label>
              <input autoComplete="off" id="delete-workspace-confirmation" onChange={(event) => setDeleteConfirmation(event.target.value)} value={deleteConfirmation} />
              {deleteError ? <p className="form-error" role="alert">{deleteError}</p> : null}
              <div className="dialog-actions"><button className="secondary-button" disabled={deleteState === "loading"} onClick={() => setDeleteTarget(null)} type="button">取消</button><button className="danger-button" disabled={!deleteImpact || deleteConfirmation !== deleteTarget.name || deleteState === "loading"} type="submit">{deleteState === "loading" ? <LoaderCircle className="spin" size={16} /> : <Trash2 size={16} />}删除</button></div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function StatusItem({ icon, label, ok, detail }: { icon: ReactNode; label: string; ok: boolean; detail: string }) {
  return (
    <div className="status-item">
      <div className={ok ? "status-icon ready" : "status-icon"}>{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{detail}</strong>
      </div>
      {ok ? <CheckCircle2 className="status-mark ok" /> : <TriangleAlert className="status-mark warn" />}
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(value));
}

function formatStatus(status: string): string {
  return ({ queued: "等待处理", accepted: "已接收", accepting: "正在接收", running: "处理中", processing: "处理中", retry_wait: "等待重试", succeeded: "已就绪", ready: "已就绪", completed: "全部完成", partial_failed: "部分完成", failed: "处理失败", rejected: "已拒绝", queue_failed: "队列失败", cancel_requested: "正在取消", canceled: "已取消", uploaded: "已上传" } as Record<string, string>)[status] ?? status;
}

function formatDocumentMeta(document: DocumentSummary): string {
  const version = document.current_version;
  if (!version) return "等待处理";
  const type = version.mime_type === "application/pdf" ? "PDF" : version.mime_type === "text/markdown" ? "Markdown" : "TXT";
  return `${type} · ${formatBytes(version.byte_size)} · ${new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(document.updated_at))}`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

function fileSelectionKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function formatCandidateFile(file: File): string {
  const extension = file.name.split(".").pop()?.toUpperCase() || "文件";
  return `${extension} · ${formatBytes(file.size)}`;
}
