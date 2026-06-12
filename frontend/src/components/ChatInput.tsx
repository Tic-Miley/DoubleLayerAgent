import { useState, useRef, useEffect, KeyboardEvent, useCallback } from 'react';
import { useSpeechRecognition } from '../hooks/useSpeechRecognition';

interface ChatInputProps {
  onSend: (text: string, model?: string, thinkingMode?: string) => void;
  onStop: () => void;
  isStreaming: boolean;
}

const MODEL_OPTIONS = [
  { value: 'deepseek-v4-flash', label: '快速', sub: 'DeepSeek Flash' },
  { value: 'deepseek-v4-pro', label: '高级', sub: 'DeepSeek Pro' },
] as const;

export function ChatInput({ onSend, onStop, isStreaming }: ChatInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 语音识别
  const {
    isSupported,
    isListening,
    interimText,
    error: speechError,
    startListening,
    stopListening,
    clearError,
  } = useSpeechRecognition({
    onFinalResult: (text: string) => {
      setInput(prev => {
        const trimmed = text.trim();
        if (!trimmed) return prev;
        if (prev && !prev.endsWith(' ') && !prev.endsWith('\n')) {
          return prev + ' ' + trimmed;
        }
        return prev + trimmed;
      });
    },
  });

  // 模型与推理模式
  const [showSettings, setShowSettings] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>(
    () => localStorage.getItem('parkinglot_model') || 'deepseek-v4-flash'
  );
  const [thinkingEnabled, setThinkingEnabled] = useState<boolean>(
    () => localStorage.getItem('parkinglot_thinking') !== 'disabled'
  );

  const settingsRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭菜单（mousedown 阶段判断，click 阶段才关闭，避免吞掉菜单项 onClick）
  useEffect(() => {
    let shouldClose = false;
    const handleMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      const inSettings = settingsRef.current?.contains(target);
      const inMenu = menuRef.current?.contains(target);
      shouldClose = !inSettings && !inMenu;
    };
    const handleClick = (e: MouseEvent) => {
      if (shouldClose) {
        setShowSettings(false);
      }
    };
    if (showSettings) {
      document.addEventListener('mousedown', handleMouseDown);
      document.addEventListener('click', handleClick);
      return () => {
        document.removeEventListener('mousedown', handleMouseDown);
        document.removeEventListener('click', handleClick);
      };
    }
  }, [showSettings]);

  // Escape 关闭菜单
  useEffect(() => {
    const handleKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setShowSettings(false);
    };
    if (showSettings) {
      document.addEventListener('keydown', handleKey);
      return () => document.removeEventListener('keydown', handleKey);
    }
  }, [showSettings]);

  const handleModelChange = useCallback((model: string) => {
    setSelectedModel(model);
    localStorage.setItem('parkinglot_model', model);
  }, []);

  const handleThinkingToggle = useCallback(() => {
    setThinkingEnabled(prev => {
      const next = !prev;
      localStorage.setItem('parkinglot_thinking', next ? 'enabled' : 'disabled');
      return next;
    });
  }, []);

  // 录音中将实时识别文本叠加到输入框末尾
  const displayValue = isListening ? input + interimText : input;

  useEffect(() => {
    if (textareaRef.current) {
      const el = textareaRef.current;
      el.style.height = 'auto';
      const style = getComputedStyle(el);
      const borderTop = parseFloat(style.borderTopWidth) || 0;
      const borderBottom = parseFloat(style.borderBottomWidth) || 0;
      el.style.height = Math.min(el.scrollHeight + borderTop + borderBottom, 120) + 'px';
    }
  }, [input, interimText]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const mode = thinkingEnabled ? 'enabled' : 'disabled';
    onSend(trimmed, selectedModel, mode);
    setInput('');
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (isStreaming || isListening) return;
      handleSend();
    }
  };

  return (
    <div className="sticky bottom-0 z-10 border-t border-[var(--color-border)] px-4 py-3 bg-[var(--color-bg)]/80 backdrop-blur-sm">
      {/* 设置菜单 — 绝对定位悬浮于底栏上方 */}
      {showSettings && (
        <div ref={menuRef} className="absolute bottom-full left-4 right-4 mb-2 z-50">
          <div className="max-w-3xl mx-auto">
            <div className="inline-block bg-[var(--color-input)] border border-[var(--color-border)] rounded-xl shadow-lg p-3 min-w-[200px]">
            {/* 模型选择 */}
            <div className="mb-3">
              <div className="text-[11px] text-[var(--color-text-tertiary)] mb-2 font-medium tracking-wide uppercase">
                模型
              </div>
              <div className="space-y-1">
                {MODEL_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => handleModelChange(opt.value)}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors
                      ${selectedModel === opt.value
                        ? 'bg-warm-yellow/15 text-warm-yellow'
                        : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg)]'
                      }`}
                  >
                    <span className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center shrink-0
                      ${selectedModel === opt.value
                        ? 'border-warm-yellow'
                        : 'border-[var(--color-border)]'
                      }`}
                    >
                      {selectedModel === opt.value && (
                        <span className="w-1.5 h-1.5 rounded-full bg-warm-yellow" />
                      )}
                    </span>
                    <span className="font-medium">{opt.label}</span>
                    <span className="text-[10px] text-[var(--color-text-tertiary)] ml-auto">{opt.sub}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* 分隔线 */}
            <div className="border-t border-[var(--color-border)] my-2" />

            {/* 推理开关 */}
            <div className="flex items-center justify-between px-1">
              <div>
                <div className="text-sm text-[var(--color-text-primary)] font-medium">推理</div>
                <div className="text-[10px] text-[var(--color-text-tertiary)]">
                  {thinkingEnabled ? '深度思考，解决复杂问题' : '不生成思维链，更迅速'}
                </div>
              </div>
              <button
                onClick={handleThinkingToggle}
                className={`relative w-9 h-5 rounded-full transition-colors shrink-0
                  ${thinkingEnabled
                    ? 'bg-warm-yellow/50'
                    : 'bg-[var(--color-border)]'
                  }`}
                role="switch"
                aria-checked={thinkingEnabled}
              >
                <span
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-all
                    ${thinkingEnabled ? 'right-0.5' : 'left-0.5'}`}
                />
              </button>
            </div>
          </div>
        </div>
        </div>
      )}

      {/* 语音错误提示 */}
      {speechError && (
        <div className="max-w-3xl mx-auto mb-2 px-1">
          <div className="text-xs text-red-400 flex items-center gap-1">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{speechError}</span>
            <button onClick={clearError} className="ml-1 underline hover:text-red-300 transition-colors">
              忽略
            </button>
          </div>
        </div>
      )}

      {/* 三列网格：左右等宽(1fr)，中间文本框(auto)，保证文本框严格居中 */}
      <div className="max-w-7xl mx-auto grid grid-cols-[1fr_auto_1fr] items-center">
        {/* 左列 — 内容靠右 */}
        <div className="flex justify-end">
          <div ref={settingsRef} className="relative shrink-0 mr-3">
            <button
              onClick={() => setShowSettings(prev => !prev)}
              disabled={isStreaming}
              className={`w-10 h-10 rounded-full border flex items-center justify-center transition-all
                ${showSettings
                  ? 'bg-warm-yellow/15 border-warm-yellow/30 text-warm-yellow'
                  : 'bg-[var(--color-input)] border-[var(--color-border)] text-[var(--color-text-tertiary)] hover:text-warm-yellow hover:border-warm-yellow/30'
                }
                disabled:opacity-30 disabled:cursor-not-allowed`}
              title="模型与推理设置"
            >
              <GearIcon />
            </button>
          </div>
        </div>

        {/* 中列 — 文本框 */}
        <textarea
          ref={textareaRef}
          value={displayValue}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isListening ? '正在聆听...' : '输入您的问题...'}
          rows={1}
          readOnly={isListening}
          disabled={isStreaming}
          className="w-full min-w-[24rem] resize-none overflow-y-auto rounded-xl bg-[var(--color-input)] border border-[var(--color-border)]
                     px-4 py-3 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-tertiary)]
                     focus:outline-none focus:border-warm-yellow/50 focus:ring-1 focus:ring-warm-yellow/20
                     disabled:opacity-50 transition-colors chat-textarea"
        />

        {/* 右列 — 内容靠左 */}
        <div className="flex justify-start">
          <div className="flex items-center gap-3 shrink-0 ml-3">
            {/* 麦克风按钮 — 仅 Chrome/Edge 可见 */}
            {isSupported && (
              <button
                onClick={isListening ? stopListening : startListening}
                disabled={isStreaming}
                className={`shrink-0 w-10 h-10 rounded-full border flex items-center justify-center transition-all
                  ${isListening
                    ? 'bg-red-500/20 border-red-500/30 text-red-400 animate-pulse'
                    : 'bg-[var(--color-input)] border-[var(--color-border)] text-[var(--color-text-tertiary)] hover:text-warm-yellow hover:border-warm-yellow/30'
                  }
                  disabled:opacity-30 disabled:cursor-not-allowed`}
                title={isListening ? '停止录音' : '语音输入'}
              >
                <MicIcon />
              </button>
            )}

            {isStreaming ? (
              <button
                onClick={onStop}
                className="shrink-0 w-10 h-10 rounded-full bg-red-500/20 border border-red-500/30
                           flex items-center justify-center text-red-400 hover:bg-red-500/30 transition-colors"
                title="停止生成"
              >
                <StopIcon />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() || isListening}
                className="shrink-0 w-10 h-10 rounded-full bg-warm-yellow/20 border border-warm-yellow/30
                           flex items-center justify-center text-warm-yellow
                           hover:bg-warm-yellow/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="发送"
              >
                <SendIcon />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  );
}