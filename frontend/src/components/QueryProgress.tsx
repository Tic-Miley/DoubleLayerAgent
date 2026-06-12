import { SourceState } from '../types/chat';

interface QueryProgressProps {
  sources: SourceState[];
}

export function QueryProgress({ sources }: QueryProgressProps) {
  if (sources.length === 0) return null;

  const total = sources.length;
  const completed = sources.filter(s => s.status === 'done' || s.status === 'error').length;
  const running = sources.filter(s => s.status === 'running').length;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const allDone = completed === total;
  const hasErrors = sources.some(s => s.status === 'error');

  return (
    <div className="mb-3 px-1">
      {/* Progress bar */}
      <div className="flex items-center gap-2 mb-1">
        <div className="flex-1 h-1.5 bg-[var(--color-border)]/30 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ease ${
              hasErrors && allDone ? 'bg-amber-400' : 'bg-blue-400'
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className="text-xs text-[var(--color-text-tertiary)] min-w-[4rem] text-right">
          {completed}/{total}
          {allDone && (hasErrors ? ' (有错误)' : ' 完成')}
          {running > 0 && ` · ${running} 进行中`}
        </span>
      </div>
    </div>
  );
}
