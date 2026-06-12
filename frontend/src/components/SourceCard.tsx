import { SourceState } from '../types/chat';
import { ChartWidget } from './ChartWidget';

interface SourceCardProps {
  source: SourceState;
}

const STATUS_CONFIG = {
  pending: { icon: '○', label: '等待中', color: 'text-[var(--color-text-tertiary)]', bg: 'bg-[var(--color-surface)]/30' },
  running: { icon: '◉', label: '查询中', color: 'text-blue-400', bg: 'bg-blue-500/5' },
  done:    { icon: '✓', label: '完成',   color: 'text-green-400', bg: 'bg-green-500/5' },
  error:   { icon: '✕', label: '失败',   color: 'text-red-400', bg: 'bg-red-500/5' },
};

export function SourceCard({ source }: SourceCardProps) {
  const cfg = STATUS_CONFIG[source.status];
  const isDone = source.status === 'done';
  const isError = source.status === 'error';
  const isRunning = source.status === 'running';

  return (
    <div
      className={`rounded-xl border p-3 transition-all duration-300 ease ${cfg.bg} ${
        isError ? 'border-red-500/30' : isDone ? 'border-green-500/20' : 'border-[var(--color-border)]/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-sm ${cfg.color} ${isRunning ? 'animate-pulse' : ''}`}>
          {cfg.icon}
        </span>
        <span className="text-xs font-medium text-[var(--color-text-primary)] truncate flex-1">
          {source.sourceName}
        </span>
        <span className={`text-xs ${cfg.color}`}>{cfg.label}</span>
      </div>

      {/* Error message */}
      {isError && source.error && (
        <div className="text-xs text-red-400 mb-2 bg-red-500/5 rounded px-2 py-1">
          {source.error}
        </div>
      )}

      {/* Summary */}
      {source.summary && (
        <div className="text-xs text-[var(--color-text-secondary)] mb-2 line-clamp-2">
          {source.summary}
        </div>
      )}

      {/* Loading skeleton */}
      {isRunning && !source.summary && (
        <div className="space-y-1.5 mb-2">
          <div className="h-2 bg-[var(--color-border)]/30 rounded animate-pulse w-3/4" />
          <div className="h-2 bg-[var(--color-border)]/20 rounded animate-pulse w-1/2" />
        </div>
      )}

      {/* L2 Charts */}
      {source.charts.length > 0 && (
        <div className="mt-2 space-y-2">
          {source.charts.map(chart => (
            <div key={chart.chartId} className="w-full" style={{ height: '150px' }}>
              <ChartWidget chart={chart} compact />
            </div>
          ))}
        </div>
      )}

      {/* L2 Tool calls (show first, rest expandable) */}
      {source.toolCalls.length > 0 && (
        <div className="mt-2 text-xs text-[var(--color-text-tertiary)]">
          {source.toolCalls.map((tc, i) => (
            <div key={i} className="flex items-center gap-1">
              <span className={tc.status === 'done' ? 'text-green-400' : tc.status === 'error' ? 'text-red-400' : 'text-blue-400'}>
                {tc.status === 'done' ? '✓' : tc.status === 'error' ? '✕' : '◉'}
              </span>
              <span>{tc.toolName}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
