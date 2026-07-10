import { useState } from 'react';
import type { ThinkingBlock as ThinkingBlockType } from '../types';

interface ThinkingBlockProps {
  block: ThinkingBlockType;
}

export function ThinkingBlock({ block }: ThinkingBlockProps) {
  const [collapsed, setCollapsed] = useState(block.collapsed);

  return (
    <details className="thinking-block" open={!collapsed}>
      <summary onClick={(e) => { e.preventDefault(); setCollapsed(!collapsed); }}>
        Thinking...
      </summary>
      <p className="thinking-content">{block.content}</p>
    </details>
  );
}
