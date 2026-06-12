import { useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ChartData } from '../types/chat';
import { ChartWidget } from './ChartWidget';

interface ChartLightboxProps {
  chart: ChartData;
  sourceName: string;
  isOpen: boolean;
  onClose: () => void;
}

export function ChartLightbox({ chart, sourceName, isOpen, onClose }: ChartLightboxProps) {
  // ESC key to close
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose],
  );

  // Body scroll lock + key listener when open
  useEffect(() => {
    if (!isOpen) return;

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label={`${sourceName} Chart 详情`}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Content panel */}
      <div className="relative z-10 w-full max-w-[54rem] mx-4 max-h-[88vh] overflow-y-auto bg-[var(--color-bg)] rounded-2xl shadow-2xl border border-[var(--color-border)]/40 animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--color-border)]/30 bg-[var(--color-surface)] rounded-t-2xl">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">
              {sourceName}
            </span>
            <span className="text-xs text-[var(--color-text-tertiary)] shrink-0">
              · Chart 详情
            </span>
          </div>

          <button
            onClick={onClose}
            className="ml-3 shrink-0 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-border)]/20 rounded-lg p-1.5 transition-colors"
            aria-label="关闭"
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M5 5l10 10M15 5L5 15" />
            </svg>
          </button>
        </div>

        {/* Chart body */}
        <div className="p-4 sm:p-5">
          <ChartWidget chart={chart} compact={false} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
