import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Message } from '../types/chat';
import { ToolCallCard } from './ToolCallCard';
import { ChartWidget } from './ChartWidget';
import { SourceCard } from './SourceCard';
import { QueryProgress } from './QueryProgress';

interface AssistantMessageProps {
  message: Message;
  onCopy: (text: string) => void;
}

export function AssistantMessage({ message, onCopy }: AssistantMessageProps) {
  const hasSources = message.sources.length > 0;
  const hasL1ToolCalls = message.toolCalls.length > 0;
  const hasL1Charts = message.charts.length > 0;
  const hasContent = !!message.content;

  return (
    <div className="px-4 sm:px-6 mb-6 group animate-slide-up">
      <div className="w-full">
        {/* L1 Tool calls */}
        {hasL1ToolCalls && (
          <div className="mb-3">
            {message.toolCalls.map((tc, i) => (
              <ToolCallCard key={`${tc.toolName}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Source query progress */}
        {hasSources && (
          <div className="mb-3">
            <QueryProgress sources={message.sources} />
          </div>
        )}

        {/* SourceCard grid */}
        {hasSources && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-3">
            {message.sources.map(source => (
              <SourceCard key={source.sourceId} source={source} />
            ))}
          </div>
        )}

        {/* Message content (L1 natural language reply) */}
        {hasContent && (
          <div className="border-l-2 border-warm-yellow/30 pl-4 py-1 mb-2">
            <div className="markdown-body text-sm text-[var(--color-text-primary)]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>

            {/* Streaming indicator */}
            {message.isStreaming && (
              <span className="inline-block w-2 h-4 bg-warm-yellow/60 animate-pulse rounded-sm ml-0.5 align-middle" />
            )}

            {/* Copy button */}
            {!message.isStreaming && message.content && (
              <button
                onClick={() => onCopy(message.content)}
                className="mt-2 text-xs text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)] transition-colors
                           opacity-0 group-hover:opacity-100"
              >
                复制
              </button>
            )}
          </div>
        )}

        {/* L1 Charts (full-width comparison charts) */}
        {hasL1Charts && (
          <div className="mt-2">
            {message.charts.map(chart => (
              <ChartWidget key={chart.chartId} chart={chart} />
            ))}
          </div>
        )}

        {/* Empty streaming state */}
        {!hasContent && !hasL1ToolCalls && !hasSources && message.isStreaming && (
          <div className="border-l-2 border-warm-yellow/30 pl-4 py-1">
            <div className="flex gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[var(--color-text-tertiary)] animate-pulse-dot" style={{ animationDelay: '0s' }} />
              <span className="w-2 h-2 rounded-full bg-[var(--color-text-tertiary)] animate-pulse-dot" style={{ animationDelay: '0.2s' }} />
              <span className="w-2 h-2 rounded-full bg-[var(--color-text-tertiary)] animate-pulse-dot" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}

        {/* Stopped indicator */}
        {!message.isStreaming && !hasContent && hasL1ToolCalls && !hasSources && (
          <div className="text-xs text-[var(--color-text-tertiary)] mt-1">已中断</div>
        )}
      </div>
    </div>
  );
}
