export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full py-16 px-6 animate-fade-in">
      <div className="text-6xl mb-6">🅿️</div>
      <h2 className="text-2xl font-semibold text-[var(--color-text-primary)] mb-2">停车场 AI 数据分析助手</h2>
      <p className="text-[var(--color-text-secondary)] text-center max-w-md mb-8 leading-relaxed">
        我可以帮您查询车位占用、分析车辆类型分布、查看历史趋势。试试下面的问题或直接输入您的需求。
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-md">
        <FeatureCard icon="📊" title="实时查询" desc="空余车位、占用率" />
        <FeatureCard icon="🔋" title="车辆分析" desc="新能源占比、类型分布" />
        <FeatureCard icon="📈" title="趋势统计" desc="日/周/月维度变化" />
        <FeatureCard icon="📋" title="楼层详情" desc="各楼层占用情况" />
      </div>
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="bg-[var(--color-surface-alt)]/60 border border-[var(--color-border)]/50 rounded-xl p-4 text-center hover:border-warm-yellow/30 transition-colors">
      <div className="text-2xl mb-1">{icon}</div>
      <div className="text-sm font-medium text-[var(--color-text-primary)]">{title}</div>
      <div className="text-xs text-[var(--color-text-tertiary)] mt-0.5">{desc}</div>
    </div>
  );
}
