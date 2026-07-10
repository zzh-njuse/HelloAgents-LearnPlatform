export type Mode = 'learning' | 'research';

export interface SSEEvent {
  type: string;
  timestamp: number;
  agent_name: string;
  data: Record<string, unknown>;
}

export type SSECallback = (event: SSEEvent) => void;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  toolCalls: ToolCallEvent[];
  thinkingBlocks: ThinkingBlock[];
  timestamp: number;
}

export interface ToolCallEvent {
  name: string;
  parameters: Record<string, unknown>;
  result?: string;
  status: 'running' | 'success' | 'error';
}

export interface ThinkingBlock {
  content: string;
  collapsed: boolean;
}

export interface ResearchStep {
  step: number;
  type: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: string;
  jsonOk?: boolean;
}
