import { useState } from 'react';
import type { ToolCallEvent } from '../types';

interface ToolCallCardProps {
  toolCall: ToolCallEvent;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const statusIcon = {
    running: '...',
    success: '✓',
    error: '✗',
  }[toolCall.status];

  return (
    <div className={`tool-call-card tool-${toolCall.status}`}>
      <div className="tool-call-header" onClick={() => setExpanded(!expanded)}>
        <span className="tool-status">{statusIcon}</span>
        <span className="tool-name">{toolCall.name}</span>
        <span className="expand-icon">{expanded ? '▲' : '▼'}</span>
      </div>
      {expanded && (
        <div className="tool-call-details">
          {toolCall.result && (
            <pre className="tool-result">{toolCall.result.slice(0, 500)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
