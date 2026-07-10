import type { Mode } from '../types';

interface ModeSwitcherProps {
  mode: Mode;
  onChange: (mode: Mode) => void;
}

export function ModeSwitcher({ mode, onChange }: ModeSwitcherProps) {
  return (
    <div className="mode-switcher">
      <button
        className={mode === 'learning' ? 'active' : ''}
        onClick={() => onChange('learning')}
      >
        Learning
      </button>
      <button
        className={mode === 'research' ? 'active' : ''}
        onClick={() => onChange('research')}
      >
        Research
      </button>
    </div>
  );
}
