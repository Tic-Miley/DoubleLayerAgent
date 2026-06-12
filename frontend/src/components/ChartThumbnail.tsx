import { ChartData } from '../types/chat';
import { ChartWidget } from './ChartWidget';

interface ChartThumbnailProps {
  chart: ChartData;
  sourceName: string;
  onClick: () => void;
}

export function ChartThumbnail({ chart, sourceName, onClick }: ChartThumbnailProps) {
  return (
    <div
      className="relative cursor-pointer group/thumb rounded-lg border border-[var(--color-border)]/30 hover:border-warm-yellow/40 hover:shadow-md transition-all duration-200 overflow-hidden"
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={`查看 ${sourceName} Chart 详情`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* Mini chart */}
      <div style={{ pointerEvents: 'none' }}>
        <ChartWidget chart={chart} thumbnail />
      </div>

      {/* Click-capturing overlay (blocks ECharts interaction) */}
      <div className="absolute inset-0" />

      {/* Hover: "click to expand" indicator */}
      <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover/thumb:bg-black/10 transition-all pointer-events-none">
        <span
          className="opacity-0 group-hover/thumb:opacity-100 transition-opacity text-xs text-white bg-black/60 backdrop-blur-sm rounded-full px-3 py-1 select-none"
          style={{ textShadow: '0 1px 2px rgba(0,0,0,0.3)' }}
        >
          🔍 点击放大
        </span>
      </div>
    </div>
  );
}
