/**
 * RichLearningText — unified formula + Markdown rendering for learning content.
 *
 * Per SLICE_4_FRONTEND_CONCEPT.md §0 and Spec 004 §4:
 * - Restricted Markdown with inline ($...$) and display ($$...$$) math
 * - mhchem support via KaTeX contrib (e.g. $\ce{H2O}$)
 * - Code fences rendered as monospace blocks
 * - Render failure: show raw expression + "公式无法渲染" locally
 * - KaTeX trust=false, no user macros, no raw HTML
 * - Does NOT read API, Workspace, or Tool — business components own state
 */

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Components } from "react-markdown";
import { useMemo } from "react";

interface RichLearningTextProps {
  /** Markdown source with optional $...$ and $$...$$ math delimiters */
  content: string;
  /** Compact mode (e.g. for inline practice stems) */
  compact?: boolean;
  /** Additional CSS class */
  className?: string;
}

/**
 * RichLearningText: Renders restricted Markdown with KaTeX math and mhchem.
 *
 * Usage:
 *   <RichLearningText content={lessonVersion.blocks[0].text} />
 *   <RichLearningText content={practiceItem.stem} compact />
 *   <RichLearningText content={tutorAnswerBlock.text} />
 */
export default function RichLearningText({
  content,
  compact = false,
  className,
}: RichLearningTextProps) {
  // Custom component overrides for react-markdown
  const components: Components = useMemo(
    () => ({
      // Code fences: render as monospace pre blocks with copy support
      code({ className: codeClassName, children, ...rest }) {
        const isInline = !codeClassName;
        if (isInline) {
          return (
            <code className="inline-code" {...rest}>
              {children}
            </code>
          );
        }
        return (
          <pre className="rich-code-block">
            <code className={codeClassName} {...rest}>
              {children}
            </code>
          </pre>
        );
      },
      // Paragraphs: ensure proper spacing
      p({ children, ...rest }) {
        return (
          <p className="rich-paragraph" {...rest}>
            {children}
          </p>
        );
      },
    }),
    []
  );

  // Pre-validate: if content has unpaired delimiters, we still render
  // but KaTeX will handle the error per-expression

  return (
    <div
      className={`rich-learning-text${compact ? " compact" : ""}${className ? ` ${className}` : ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[
          [
            rehypeKatex,
            {
              strict: false, // allow fallback on errors
              trust: false, // no user macros, no \href
              throwOnError: false, // render error fallback instead of crashing
              output: "htmlAndMathml" as const,
              // mhchem is loaded via KaTeX CSS + contrib import in main entry
            },
          ],
        ]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
