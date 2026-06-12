import { useState } from 'react';
import { ToolCallEvent } from '../types/chat';

interface ToolCallCardProps {
  toolCall: ToolCallEvent;
}

// ── 基础标签映射 (v2 工具) ────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  get_config: '获取停车场配置',
  query_aggregation: '执行聚合查询',
  get_vehicle: '查询车辆信息',
  sql_query: '执行SQL查询',
  render_chart: '生成统计图表',
};

// ── 参数感知标签推导 ──────────────────────────────────

const GROUP_BY_LABELS: Record<string, string> = {
  vehicle_type: '按能源类型统计',
  floor: '按楼层统计',
  date: '按日统计趋势',
  hour: '按时段分布',
  day_of_week: '按星期分布',
  month: '按月汇总',
};

function deriveLabel(toolName: string, args?: Record<string, unknown>): string | null {
  switch (toolName) {
    case 'query_aggregation': {
      // 无 group_by + active_only → 当前空余车位
      if (args?.active_only === true && !args?.group_by) {
        return '查询当前空余车位';
      }
      // 有 group_by
      const gb = args?.group_by as string | undefined;
      if (gb && GROUP_BY_LABELS[gb]) {
        let label = GROUP_BY_LABELS[gb];
        // 附加日期范围
        if (args?.date_from) {
          const from = args.date_from as string;
          const to = args.date_to as string;
          if (from && to && from === to) {
            label += ` (${from})`;
          } else if (from && to) {
            label += ` (${from} ~ ${to})`;
          } else if (from) {
            label += ` (${from}起)`;
          }
        }
        return label;
      }
      // active_only=false 无 group_by → 历史汇总
      if (args?.active_only === false && !args?.group_by) {
        return '查询历史汇总统计';
      }
      return null; // fallback to TOOL_LABELS
    }

    case 'render_chart': {
      try {
        const option = args?.option as Record<string, unknown> | undefined;
        const series = option?.series as Array<Record<string, unknown>> | undefined;
        const chartType = series?.[0]?.type as string | undefined;
        if (chartType === 'pie') return '生成饼图';
        if (chartType === 'line') return '生成折线图';
        if (chartType === 'bar') return '生成柱状图';
      } catch { /* ignore parse errors */ }
      return null;
    }

    case 'get_vehicle': {
      const plate = args?.plate as string | undefined;
      if (plate) return `查询车辆 ${plate}`;
      return null;
    }

    case 'sql_query': {
      // 尝试从 SQL 中提取关键信息
      const query = args?.query as string | undefined;
      if (query) {
        const upper = query.toUpperCase();
        if (upper.includes('COUNT') && upper.includes('GROUP BY')) {
          return '执行分组统计查询';
        }
        if (upper.includes('AVG') || upper.includes('AVERAGE')) {
          return '执行平均值查询';
        }
        if (upper.includes('WHERE') && upper.includes('NULL')) {
          return '查询在场车辆';
        }
        return '执行自定义SQL查询';
      }
      return null;
    }

    default:
      return null;
  }
}

// ── 组件 ──────────────────────────────────────────────

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  // 标签优先级: 后端 message > 前端参数感知 > 静态映射 > 原始名称
  const label =
    toolCall.message ||
    deriveLabel(toolCall.toolName, toolCall.arguments) ||
    TOOL_LABELS[toolCall.toolName] ||
    toolCall.toolName;

  const isRunning = toolCall.status === 'running';
  const isError = toolCall.status === 'error';

  return (
    <div
      className={`mb-2 text-xs rounded-lg border overflow-hidden transition-all duration-200 animate-slide-up
        ${isError ? 'border-red-500/30 bg-red-500/5' : 'border-[var(--color-border)]/50 bg-[var(--color-surface)]/40'}`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--color-surface-hover)] transition-colors"
      >
        {/* Status icon */}
        {isRunning ? (
          <span className="w-4 h-4 flex items-center justify-center">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-400 animate-pulse-dot" />
          </span>
        ) : isError ? (
          <span className="text-red-400">✕</span>
        ) : (
          <span className="text-green-400">✓</span>
        )}

        <span className={`flex-1 ${isError ? 'text-red-300' : 'text-[var(--color-text-secondary)]'}`}>
          {isRunning ? `正在${label}...` : isError ? `${label}失败` : `${label}完成`}
        </span>

        {(toolCall.resultPreview || toolCall.error) && (
          <span className="text-[var(--color-text-tertiary)]">
            <Chevron expanded={expanded} />
          </span>
        )}
      </button>

      {expanded && (
        <div className="px-3 py-2 border-t border-[var(--color-border)]/30 bg-[var(--color-surface-code)] font-mono text-xs text-[var(--color-text-secondary)]">
          {toolCall.error ? (
            <div className="text-red-400">{toolCall.error}</div>
          ) : toolCall.resultPreview ? (
            <pre className="whitespace-pre-wrap break-all">
              {typeof toolCall.resultPreview === 'string'
                ? toolCall.resultPreview
                : JSON.stringify(toolCall.resultPreview, null, 2)}
            </pre>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Chevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
