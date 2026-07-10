import { useState, useCallback, useRef } from 'react';
import { createSSEStream } from '../services/api';
import type { Mode, ChatMessage, ThinkingBlock } from '../types';

export function useSSE() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback((mode: Mode, text: string, sessionId: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(), role: 'user', content: text,
      toolCalls: [], thinkingBlocks: [], timestamp: Date.now(),
    };
    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID(), role: 'assistant', content: '',
      toolCalls: [], thinkingBlocks: [], timestamp: Date.now(),
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    const thinkingBuffer: ThinkingBlock[] = [];

    abortRef.current = createSSEStream(
      mode, text, sessionId,
      (event) => {
        setMessages(prev => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx < 0) return updated;

          switch (event.type) {
            case 'llm_chunk':
              updated[lastIdx] = {
                ...updated[lastIdx],
                content: updated[lastIdx].content + (event.data.chunk as string || ''),
              };
              break;

            case 'thinking':
              thinkingBuffer.push({
                content: event.data.content as string || '',
                collapsed: false,
              });
              updated[lastIdx] = {
                ...updated[lastIdx],
                thinkingBlocks: [...thinkingBuffer],
              };
              break;

            case 'tool_call_start':
              updated[lastIdx] = {
                ...updated[lastIdx],
                toolCalls: [
                  ...updated[lastIdx].toolCalls,
                  {
                    name: event.data.tool_name as string || '?',
                    parameters: event.data as Record<string, unknown>,
                    status: 'running' as const,
                  },
                ],
              };
              break;

            case 'tool_call_finish':
              updated[lastIdx] = {
                ...updated[lastIdx],
                toolCalls: updated[lastIdx].toolCalls.map(tc =>
                  tc.name === (event.data.tool_name as string) && tc.status === 'running'
                    ? { ...tc, status: 'success' as const, result: event.data.result as string }
                    : tc
                ),
              };
              break;

            case 'agent_finish':
              if (event.data.result && !updated[lastIdx].content) {
                updated[lastIdx] = {
                  ...updated[lastIdx],
                  content: event.data.result as string,
                };
              }
              break;

            case 'error':
              updated[lastIdx] = {
                ...updated[lastIdx],
                content: updated[lastIdx].content +
                  `\n\n_Error: ${event.data.error as string}_`,
              };
              break;
          }
          return updated;
        });
      },
      (err) => {
        setIsStreaming(false);
        setMessages(prev => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0) {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: updated[lastIdx].content +
                `\n\n_Connection error: ${err.message}_`,
            };
          }
          return updated;
        });
      },
      () => {
        setIsStreaming(false);
      },
    );
  }, []);

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return { messages, isStreaming, sendMessage, cancelStream };
}
