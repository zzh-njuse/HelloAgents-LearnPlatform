import type { Mode, SSECallback } from '../types';

const API_BASE = '/api';

export function createSSEStream(
  mode: Mode,
  message: string,
  sessionId: string,
  onEvent: SSECallback,
  onError: (err: Error) => void,
  onComplete: () => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, message, session_id: sessionId }),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      const errText = await response.text();
      onError(new Error(`HTTP ${response.status}: ${errText}`));
      return;
    }
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) { onComplete(); break; }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ') && eventType) {
          try {
            const parsed = JSON.parse(line.slice(6));
            onEvent({ type: eventType, ...parsed });
          } catch { /* skip malformed JSON */ }
          eventType = '';
        }
        // Skip SSE comments (lines starting with ':')
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') onError(err);
  });

  return controller;
}

export async function sendChat(mode: Mode, message: string, sessionId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, message, session_id: sessionId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const data = await res.json();
  return data.response;
}
