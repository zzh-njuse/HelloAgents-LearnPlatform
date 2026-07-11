import {
  Activity,
  BookOpenCheck,
  CheckCircle2,
  Database,
  FileStack,
  FolderOpen,
  FolderPlus,
  HardDrive,
  LoaderCircle,
  Plus,
  RefreshCw,
  Server,
  TriangleAlert
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import {
  createWorkspace,
  fetchReadiness,
  fetchSystemInfo,
  fetchWorkspaces,
  Readiness,
  SystemInfo,
  Workspace
} from "../lib/api";

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

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedId) ?? null,
    [selectedId, workspaces]
  );

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
              <FileStack size={21} />
            </div>

            {selectedWorkspace ? (
              <div className="workspace-detail">
                <dl>
                  <div><dt>Slug</dt><dd>{selectedWorkspace.slug}</dd></div>
                  <div><dt>创建时间</dt><dd>{formatDate(selectedWorkspace.created_at)}</dd></div>
                  <div><dt>资料</dt><dd>0</dd></div>
                </dl>
                <div className="material-empty">
                  <div className="empty-icon"><FileStack size={24} /></div>
                  <div>
                    <strong>资料入口将在 Stage 2 接入</strong>
                    <p>当前 workspace 已经具备稳定身份，可承载后续资料、索引与学习记录。</p>
                  </div>
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
      </main>
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
