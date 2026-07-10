import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import type { ChatMessage } from '../types';
import { ToolCallCard } from './ToolCallCard';
import { ThinkingBlock } from './ThinkingBlock';

interface MessageCardProps {
  message: ChatMessage;
}

export function MessageCard({ message }: MessageCardProps) {
  return (
    <div className={`message-card message-${message.role}`}>
      <div className="message-header">
        <span className="message-role">
          {message.role === 'user' ? 'You' : message.role === 'assistant' ? 'AI' : 'System'}
        </span>
        <span className="message-time">
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {message.thinkingBlocks.map((tb, i) => (
        <ThinkingBlock key={i} block={tb} />
      ))}

      <div className="message-content">
        {message.content ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeKatex]}
          >
            {message.content}
          </ReactMarkdown>
        ) : message.role === 'assistant' ? (
          <span className="streaming-indicator">...</span>
        ) : null}
      </div>

      {message.toolCalls.map((tc, i) => (
        <ToolCallCard key={i} toolCall={tc} />
      ))}
    </div>
  );
}
