import { useTheme } from '../hooks/useTheme';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      onClick={toggleTheme}
      role="switch"
      aria-checked={!isDark}
      aria-label={isDark ? '切换至浅色模式' : '切换至深色模式'}
      title={isDark ? '切换至浅色模式' : '切换至深色模式'}
      className={`
        relative flex items-center shrink-0
        w-14 h-7 rounded-full
        transition-colors duration-300
        focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg)]
        ${isDark
          ? 'bg-[var(--color-surface-alt)] ring-warm-yellow/50'
          : 'bg-[var(--color-border)] ring-warm-yellow/50'
        }
      `}
    >
      {/* Track texture /刻度线 */}
      <span className="absolute inset-0 rounded-full overflow-hidden pointer-events-none">
        <span
          className={`
            absolute inset-0 opacity-20
            ${isDark ? 'bg-gradient-to-r from-transparent via-white/5 to-transparent' : 'bg-gradient-to-r from-transparent via-black/5 to-transparent'}
          `}
        />
      </span>

      {/* Left icon: diamond (暗) */}
      <span
        className={`
          absolute left-1.5 z-10 pointer-events-none
          transition-all duration-300
          ${isDark ? 'opacity-100 scale-100' : 'opacity-30 scale-75'}
        `}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"
          className={isDark ? 'text-warm-yellow' : 'text-[var(--color-text-tertiary)]'}
        >
          <polygon points="5,1 9,5 5,9 1,5" />
        </svg>
      </span>

      {/* Right icon: diamond outline (亮) */}
      <span
        className={`
          absolute right-1.5 z-10 pointer-events-none
          transition-all duration-300
          ${isDark ? 'opacity-30 scale-75' : 'opacity-100 scale-100'}
        `}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.2"
          className={isDark ? 'text-[var(--color-text-tertiary)]' : 'text-warm-yellow'}
        >
          <polygon points="5,1 9,5 5,9 1,5" />
        </svg>
      </span>

      {/* Sliding knob — octagonal amber */}
      <span
        className={`
          absolute z-20
          w-[18px] h-[18px]
          rounded-[4px] rotate-[22.5deg]
          transition-all duration-300 ease-out
          shadow-md
          ${isDark
            ? 'left-[4px] bg-warm-yellow shadow-warm-yellow/25'
            : 'left-[calc(100%-22px)] bg-warm-yellow shadow-warm-yellow/25'
          }
        `}
      />
    </button>
  );
}
