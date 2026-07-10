import { useState, useRef, useEffect, type FormEvent } from 'react';
import type { ChatMessage } from '../types';
import { MessageCard } from './MessageCard';

interface ChatViewProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function ChatView({ messages, isStreaming, onSend, onCancel }: ChatViewProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSend(input.trim());
    setInput('');
  };

  return (
    <div className="chat-view">
      <div className="messages-list">
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>Academic AI Companion</h2>
            <p>选择模式后开始提问，支持学习模式和论文研究模式。</p>
          </div>
        )}
        {messages.map(msg => (
          <MessageCard key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask a question..."
          disabled={isStreaming}
        />
        {isStreaming
          ? <button type="button" onClick={onCancel} className="btn-stop">Stop</button>
          : <button type="submit" disabled={!input.trim()}>Send</button>
        }
      </form>
    </div>
  );
}
