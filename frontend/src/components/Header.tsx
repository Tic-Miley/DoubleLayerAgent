import { ThemeToggle } from './ThemeToggle';

export function Header() {
  return (
    <header className="sticky top-0 z-10 bg-[var(--color-bg)]/90 backdrop-blur-sm border-b border-[var(--color-border)]/20">
      <div className="max-w-[54rem] mx-auto flex items-center justify-between px-4 sm:px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-xl">🏙️</span>
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">
            城市数据助手
          </h1>
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}
