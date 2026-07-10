import type { ResearchStep } from '../types';

interface ResearchPanelProps {
  steps: ResearchStep[];
}

export function ResearchPanel({ steps }: ResearchPanelProps) {
  const statusLabel = (status: string) => {
    switch (status) {
      case 'completed': return '✓';
      case 'running': return '•';
      case 'failed': return '✗';
      default: return '—';
    }
  };

  return (
    <div className="research-panel">
      <h3>Research Pipeline</h3>
      <div className="pipeline-steps">
        {(steps.length === 0 ? [
          { step: 1, type: 'search', description: 'Search papers', status: 'pending' as const },
          { step: 2, type: 'filter', description: 'Filter & score', status: 'pending' as const },
          { step: 3, type: 'analyze', description: 'Deep analysis', status: 'pending' as const },
          { step: 4, type: 'synthesize', description: 'Synthesize report', status: 'pending' as const },
        ] : steps).map((s, i) => (
          <div key={i} className={`pipeline-step step-${s.status}`}>
            <div className="step-indicator">{statusLabel(s.status)}</div>
            <span className="step-type">{s.type}</span>
            {s.description && <span className="step-desc">{s.description}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
