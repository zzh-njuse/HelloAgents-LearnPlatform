/**
 * CodeWorkbench — unified CodeMirror 6 code editor component.
 *
 * Per SLICE_4_FRONTEND_CONCEPT.md §1 and Spec 004 §11:
 * - CodeMirror 6 with language extensions (Python, Java, C++)
 * - Line numbers, bracket matching, Tab indentation
 * - Stable height, readonly mode, no business-logic awareness
 * - Used by CodeLabPanel, PracticePanel (coding items), and TutorPanel (code_observation)
 * - Does NOT read API, Workspace, or Tool — business components own state and commands
 */

import { useMemo } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { java } from "@codemirror/lang-java";
import { cpp } from "@codemirror/lang-cpp";
import { keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { basicSetup } from "@uiw/react-codemirror";
import type { Extension } from "@codemirror/state";

/** Supported languages matching the execution contract */
const LANGUAGES = ["python", "java", "cpp"] as const;
type Language = (typeof LANGUAGES)[number];

const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  java: "Java",
  cpp: "C++",
};

/** Placeholder code for each language */
const PLACEHOLDER_CODE: Record<Language, string> = {
  python: "# Enter Python code\nprint('Hello, World!')",
  java: '// Enter Java code\nclass Main {\n  public static void main(String[] args) {\n    System.out.println("Hello, World!");\n  }\n}',
  cpp: '// Enter C++ code\n#include <iostream>\nint main() {\n  std::cout << "Hello, World!" << std::endl;\n  return 0;\n}',
};

/**
 * Get the CodeMirror language extension for a given language.
 */
function getLanguageExtension(language: Language) {
  switch (language) {
    case "python":
      return python();
    case "java":
      return java();
    case "cpp":
      return cpp();
    default:
      return [];
  }
}

interface CodeWorkbenchProps {
  /** Current code value */
  value: string;
  /** Callback when code changes */
  onChange: (value: string) => void;
  /** Programming language for syntax highlighting */
  language: Language | string;
  /** Read-only mode (e.g. for viewing reference code or output) */
  readOnly?: boolean;
  /** Placeholder text when empty */
  placeholder?: string;
  /** Minimum height in pixels (default 200) */
  minHeight?: number;
  /** Maximum height in pixels (default 500) */
  maxHeight?: number;
  /** Additional CSS class */
  className?: string;
}

/**
 * CodeWorkbench: A CodeMirror 6-based code editor with language support.
 *
 * Usage:
 *   <CodeWorkbench
 *     value={sourceCode}
 *     onChange={setSourceCode}
 *     language="python"
 *   />
 *   <CodeWorkbench
 *     value={referenceCode}
 *     onChange={() => {}}
 *     language="java"
 *     readOnly
 *   />
 */
export default function CodeWorkbench({
  value,
  onChange,
  language,
  readOnly = false,
  placeholder,
  minHeight = 200,
  maxHeight = 500,
  className,
}: CodeWorkbenchProps) {
  // Normalize language to one of the supported values
  const normalizedLanguage: Language = LANGUAGES.includes(language as Language)
    ? (language as Language)
    : "python";

  // Build extensions: basic setup + language + tab indent
  const extensions = useMemo(() => {
    const exts: Extension[] = [basicSetup(), getLanguageExtension(normalizedLanguage)];
    if (!readOnly) {
      exts.push(keymap.of([indentWithTab]));
    }
    return exts;
  }, [normalizedLanguage, readOnly]);

  return (
    <div
      className={`code-workbench${className ? ` ${className}` : ""}`}
      style={{ height: minHeight, maxHeight }}
    >
      <CodeMirror
        value={value}
        onChange={onChange}
        extensions={extensions}
        readOnly={readOnly}
        placeholder={placeholder ?? PLACEHOLDER_CODE[normalizedLanguage]}
        basicSetup={false} // We provide our own basicSetup in extensions
        height={`${minHeight}px`}
        style={{
          fontSize: "13px",
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace",
          height: minHeight,
          maxHeight,
        }}
      />
    </div>
  );
}

export { LANGUAGES, LANGUAGE_LABELS, PLACEHOLDER_CODE };
export type { Language };
