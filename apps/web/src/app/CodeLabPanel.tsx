/**
 * CodeLabPanel — Slice 4 code execution lab UI.
 *
 * Per SLICE_4_FRONTEND_CONCEPT.md:
 * - Language selector: Python / Java / C++
 * - Code editor + optional stdin
 * - "Run" button (user-triggered only)
 * - Output: compile_output, stdout, stderr, exit_code, duration, truncation flags
 * - Run history and delete
 * - "Use for next Tutor question" checkbox (default off)
 */

import { useState, useEffect, useCallback } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import {
  createCodeRun,
  listCodeRuns,
  getCodeRun,
  cancelCodeRun,
  deleteCodeRun,
  getMcpPolicy,
  patchMcpPolicy,
  type CodeRun,
  type CodeRunDetail,
} from "../lib/api";
import CodeWorkbench from "./CodeWorkbench";

interface CodeLabPanelProps {
  workspaceId: string;
  /** Per correction 004 §6: callback accepts nullable selection.
   *  Checked: (runId, language). Unchecked: null. */
  onCodeRunForTutor?: (selection: { runId: string; language: string } | null) => void;
}

const LANGUAGES = ["python", "java", "cpp"] as const;
type Language = (typeof LANGUAGES)[number];

const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  java: "Java",
  cpp: "C++",
};

const PLACEHOLDER_CODE: Record<Language, string> = {
  python: "# Enter Python code\nprint('Hello, World!')",
  java: '// Enter Java code\nclass Main {\n  public static void main(String[] args) {\n    System.out.println("Hello, World!");\n  }\n}',
  cpp: '// Enter C++ code\n#include <iostream>\nint main() {\n  std::cout << "Hello, World!" << std::endl;\n  return 0;\n}',
};

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "canceled",
  "completed",
  "compile_error",
  "runtime_error",
  "timed_out",
  "output_limited",
]);

export default function CodeLabPanel({
  workspaceId,
  onCodeRunForTutor,
}: CodeLabPanelProps) {
  const [language, setLanguage] = useState<Language>("python");
  const [sourceCode, setSourceCode] = useState(PLACEHOLDER_CODE.python);
  const [stdin, setStdin] = useState("");
  const [currentRun, setCurrentRun] = useState<CodeRunDetail | null>(null);
  const [runs, setRuns] = useState<CodeRun[]>([]);
  const [useForTutor, setUseForTutor] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);
  const [codeExecutionEnabled, setCodeExecutionEnabled] = useState(false);

  const fetchRuns = useCallback(async () => {
    try {
      const result = await listCodeRuns(workspaceId, 20, 0);
      setRuns(result);
    } catch {
      // Silently ignore — runs list is non-critical
    }
  }, [workspaceId]);

  useEffect(() => {
    fetchRuns();
    void getMcpPolicy(workspaceId)
      .then((policy) => setCodeExecutionEnabled(policy.code_execution_enabled))
      .catch(() => setCodeExecutionEnabled(false));
    // Per correction 005 §5: workspace change invalidates all runs
    setUseForTutor(false);
    setFocused(false);
    onCodeRunForTutor?.(null);
    setCurrentRun(null);
  }, [fetchRuns, onCodeRunForTutor, workspaceId]);

  const changeCodeExecutionPolicy = async (enabled: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const policy = await patchMcpPolicy(workspaceId, { code_execution_enabled: enabled });
      setCodeExecutionEnabled(policy.code_execution_enabled);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法更新代码执行设置");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!focused) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocused(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [focused]);

  // Poll running job
  useEffect(() => {
    if (!currentRun || TERMINAL_STATUSES.has(currentRun.status)) return;
    const interval = setInterval(async () => {
      try {
        const detail = await getCodeRun(workspaceId, currentRun.id);
        setCurrentRun(detail);
        if (TERMINAL_STATUSES.has(detail.status)) {
          fetchRuns();
        } else {
          // Per correction 005 §5: Run refreshed to non-terminal state
          // must clear the tutor selection
          setUseForTutor(false);
          onCodeRunForTutor?.(null);
        }
      } catch {
        // Ignore poll errors
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [currentRun, workspaceId, fetchRuns, onCodeRunForTutor]);

  const handleLanguageChange = (lang: Language) => {
    setLanguage(lang);
    setSourceCode(PLACEHOLDER_CODE[lang]);
    setStdin("");
  };

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const idempotencyKey = `code-run-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const run = await createCodeRun(
        workspaceId,
        { language, source_code: sourceCode, stdin },
        idempotencyKey,
      );
      setCurrentRun({ ...run, source_code: sourceCode, stdin, compile_output: "", stdout: "", stderr: "" });
      fetchRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行失败");
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!currentRun) return;
    try {
      await cancelCodeRun(workspaceId, currentRun.id);
      setCurrentRun(null);
      fetchRuns();
    } catch {
      // Ignore
    }
  };

  const handleDelete = async (runId: string) => {
    try {
      await deleteCodeRun(workspaceId, runId);
      fetchRuns();
      if (currentRun?.id === runId) {
        setCurrentRun(null);
        // Per correction 005 §5: deleting the selected Run must clear
        // the selection and notify parent with null
        setUseForTutor(false);
        onCodeRunForTutor?.(null);
      }
    } catch {
      // Ignore
    }
  };

  const handleSelectRun = async (runId: string) => {
    try {
      const detail = await getCodeRun(workspaceId, runId);
      setCurrentRun(detail);
      // Per correction 005 §5: selecting a different Run must clear
      // the tutor selection. The new Run may not be terminal yet,
      // and even if it is, the user must explicitly re-check.
      // Also clear if the Run is not in a terminal state.
      setUseForTutor(false);
      onCodeRunForTutor?.(null);
    } catch {
      // Ignore
    }
  };

  return (
    <div className={`code-lab-panel${focused ? " code-lab-focused" : ""}`}>
      <div className="code-lab-heading">
        <div><strong>代码实验室</strong><small>在隔离执行环境中运行 Python、Java 或 C++</small></div>
        <button className="icon-button" onClick={() => setFocused((value) => !value)} title={focused ? "退出专注模式" : "专注编写代码"} type="button">{focused ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>
      </div>
      <label className="source-choice code-execution-policy"><input checked={codeExecutionEnabled} disabled={loading} onChange={(event) => void changeCodeExecutionPolicy(event.target.checked)} type="checkbox" />允许此工作区将代码发送到自托管隔离执行环境</label>
      {/* Language selector */}
      <div className="code-lab-language-selector">
        {LANGUAGES.map((lang) => (
          <button
            key={lang}
            className={`lang-btn ${language === lang ? "active" : ""}`}
            onClick={() => handleLanguageChange(lang)}
          >
            {LANGUAGE_LABELS[lang]}
          </button>
        ))}
      </div>

      {/* Code editor — CodeMirror 6 via CodeWorkbench (Spec 004 §11) */}
      <div className="code-lab-editor">
        <CodeWorkbench
          value={sourceCode}
          onChange={setSourceCode}
          language={language}
          placeholder={PLACEHOLDER_CODE[language]}
          minHeight={240}
          maxHeight={500}
        />
      </div>

      {/* Stdin (optional) */}
      <div className="code-lab-stdin">
        <label>
          标准输入 (stdin)
          <textarea
            className="stdin-editor"
            value={stdin}
            onChange={(e) => setStdin(e.target.value)}
            placeholder="可选标准输入"
            rows={2}
          />
        </label>
      </div>

      {/* Run button & status */}
      <div className="code-lab-actions">
        <button
          className="run-btn"
          onClick={handleRun}
          disabled={!codeExecutionEnabled || loading || !sourceCode.trim()}
        >
          {loading ? "提交中…" : "运行"}
        </button>
        {currentRun && !TERMINAL_STATUSES.has(currentRun.status) && (
          <button className="cancel-btn" onClick={handleCancel}>
            取消
          </button>
        )}
        {currentRun && (
          <span className="run-status">状态：{currentRun.status}</span>
        )}
        {error && <span className="run-error">{error}</span>}
      </div>

      {/* Output */}
      {currentRun && TERMINAL_STATUSES.has(currentRun.status) && (
        <div className="code-lab-output">
          {currentRun.compile_output && (
            <div className="output-section">
              <h4>编译输出</h4>
              <pre className="output-text compile-output">
                {currentRun.compile_output}
              </pre>
            </div>
          )}
          {currentRun.stdout && (
            <div className="output-section">
              <h4>
                标准输出
                {currentRun.stdout_truncated && " (已截断)"}
              </h4>
              <pre className="output-text stdout">{currentRun.stdout}</pre>
            </div>
          )}
          {currentRun.stderr && (
            <div className="output-section">
              <h4>
                标准错误
                {currentRun.stderr_truncated && " (已截断)"}
              </h4>
              <pre className="output-text stderr">{currentRun.stderr}</pre>
            </div>
          )}
          <div className="output-meta">
            退出码：{currentRun.exit_code ?? "N/A"}
            {currentRun.duration_ms != null &&
              ` | 耗时：${currentRun.duration_ms}ms`}
            {currentRun.runtime && ` | 运行时：${currentRun.runtime}`}
          </div>
        </div>
      )}

      {/* Use for Tutor checkbox */}
      {currentRun && TERMINAL_STATUSES.has(currentRun.status) && onCodeRunForTutor && (
        <div className="code-lab-tutor-option">
          <label>
            <input
              type="checkbox"
              checked={useForTutor}
              onChange={(e) => {
                const checked = e.target.checked;
                setUseForTutor(checked);
                // Per correction 004 §6: unchecking must notify parent with null
                if (checked) {
                  onCodeRunForTutor({ runId: currentRun.id, language: currentRun.language });
                } else {
                  onCodeRunForTutor(null);
                }
              }}
            />
            用于下一次 Tutor 提问
          </label>
        </div>
      )}

      {/* Run history */}
      {runs.length > 0 && (
        <div className="code-lab-history">
          <h4>运行历史</h4>
          {runs.map((run) => (
            <div key={run.id} className="run-history-item">
              <button
                className="history-select"
                onClick={() => handleSelectRun(run.id)}
              >
                {LANGUAGE_LABELS[run.language as Language] ?? run.language} ·{" "}
                {run.status} ·{" "}
                {new Date(run.created_at).toLocaleTimeString()}
              </button>
              <button
                className="history-delete"
                onClick={() => handleDelete(run.id)}
              >
                删除
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
