import { useState, useCallback } from 'react';
import type { Mode, ResearchStep } from './types';
import { useSSE } from './hooks/useSSE';
import { ModeSwitcher } from './components/ModeSwitcher';
import { ChatView } from './components/ChatView';
import { ResearchPanel } from './components/ResearchPanel';
import './App.css';

const DEFAULT_PIPELINE: ResearchStep[] = [
  { step: 1, type: 'search', description: 'Search papers', status: 'pending' },
  { step: 2, type: 'filter', description: 'Filter & score', status: 'pending' },
  { step: 3, type: 'analyze', description: 'Deep analysis', status: 'pending' },
  { step: 4, type: 'synthesize', description: 'Synthesize report', status: 'pending' },
];

function App() {
  const [mode, setMode] = useState<Mode>('learning');
  const [sessionId] = useState(() => crypto.randomUUID());
  const [researchSteps, setResearchSteps] = useState<ResearchStep[]>(DEFAULT_PIPELINE);
  const { messages, isStreaming, sendMessage, cancelStream } = useSSE();

  const handleSend = useCallback((text: string) => {
    if (mode === 'research') {
      setResearchSteps(DEFAULT_PIPELINE.map(s => ({ ...s, status: 'pending' as const })));
    }
    sendMessage(mode, text, sessionId);
  }, [mode, sessionId, sendMessage]);

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Academic AI Companion</h1>
        <ModeSwitcher mode={mode} onChange={setMode} />
      </header>
      <main className="app-main">
        {mode === 'research' && (
          <aside className="app-sidebar">
            <ResearchPanel steps={researchSteps} />
          </aside>
        )}
        <ChatView
          messages={messages}
          isStreaming={isStreaming}
          onSend={handleSend}
          onCancel={cancelStream}
        />
      </main>
    </div>
  );
}

export default App;
