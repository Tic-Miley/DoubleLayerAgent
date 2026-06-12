interface QuickQuestionsProps {
  onSelect: (question: string) => void;
  disabled?: boolean;
}

const QUESTIONS = [
  '附近停车场的新能源车占比？',
  '食堂和医院现在各有多少人？',
  '方圆5公里有哪些停车场？',
  '三个停车场的占用率对比',
];

const ICONS = ['🔋', '🏥', '🗺️', '📊'];

export function QuickQuestions({ onSelect, disabled }: QuickQuestionsProps) {
  return (
    <div className="flex flex-wrap gap-2 px-6 py-3 justify-center">
      {QUESTIONS.map((q, i) => (
        <button
          key={q}
          onClick={() => onSelect(q)}
          disabled={disabled}
          className="flex items-center gap-1.5 px-4 py-2 rounded-full text-sm
                     bg-[var(--color-surface)] border border-[var(--color-border)]/50 text-[var(--color-text-secondary)]
                     hover:border-warm-yellow/40 hover:text-warm-yellow
                     disabled:opacity-40 disabled:cursor-not-allowed
                     transition-all duration-200"
        >
          <span>{ICONS[i]}</span>
          <span>{q}</span>
        </button>
      ))}
    </div>
  );
}
