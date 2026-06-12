import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { ChartData } from '../types/chat';
import { useTheme } from '../hooks/useTheme';

interface ChartWidgetProps {
  chart: ChartData;
  compact?: boolean;
}

// ── 浅色模式配色（新默认）──
const LIGHT_DATA_COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2'];
const LIGHT_TEXT_PRIMARY = '#2c2c2c';
const LIGHT_TEXT_SECONDARY = '#6b6560';
const LIGHT_BORDER = '#d9d4cc';
const LIGHT_TOOLTIP_BG = 'rgba(255, 255, 255, 0.95)';

// ── 深色模式配色 ──
const DARK_DATA_COLORS = ['#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#22d3ee'];
const DARK_TEXT_PRIMARY = '#e2e8f0';
const DARK_TEXT_SECONDARY = '#94a3b8';
const DARK_BORDER = '#2a2a5a';
const DARK_TOOLTIP_BG = 'rgba(26, 26, 46, 0.95)';

type PlainObject = Record<string, unknown>;

interface AxisPatchArgs {
  axis: PlainObject;
  labelColor: string;
  lineColor: string;
  splitLineColor: string;
}

// ── 布局冲突检测辅助 ──

/** 检查任意 yAxis 是否设置了 name（如 "入场车次"） */
function yAxisHasName(yAxis: unknown): boolean {
  if (!yAxis) return false;
  if (Array.isArray(yAxis)) {
    return (yAxis as PlainObject[]).some(
      a => a && typeof a === 'object' && typeof a.name === 'string' && (a.name as string).length > 0,
    );
  }
  if (typeof yAxis === 'object') {
    const a = yAxis as PlainObject;
    return typeof a.name === 'string' && (a.name as string).length > 0;
  }
  return false;
}

/** 检查 legend 是否处于顶部且可能与长标题冲突（顶部居中或顶部居右） */
function legendAtTopRight(legend: unknown): boolean {
  if (!legend || typeof legend !== 'object') return false;
  const l = legend as PlainObject;
  // 已明确移到底部 → 无冲突
  if (l.bottom !== undefined || l.top === 'bottom') return false;
  const isTop = l.top === undefined || l.top === 'top' || l.top === 0;
  const isCenter = l.left === undefined || l.left === 'center';
  const isRight = l.left === 'right' || l.right === 0 || l.right === 'right';
  return isTop && (isCenter || isRight);
}

/**
 * 将 grid 某一边的边距归一化到合理范围。
 * LLM 生成的百分比值（如 left: '20%'）是为全屏仪表盘设计的，
 * 在聊天气泡 (~320px) 中浪费大量空间。超过上限则回退为紧凑默认值。
 */
function normalizeGridSide(
  value: unknown,
  tightDefault: number,
  maxAbsolute: number,
  maxPercent: number,
): number | string {
  if (value === undefined || value === 'auto') return tightDefault;
  if (typeof value === 'string' && value.endsWith('%')) {
    return parseFloat(value) > maxPercent ? tightDefault : value;
  }
  if (typeof value === 'number') {
    return value > maxAbsolute ? tightDefault : value;
  }
  return tightDefault;
}

/**
 * 修复常见的 ECharts 布局冲突：
 * 1. Grid 边距归一化 — 压制 LLM 生成的过大百分比/绝对值
 * 2. 副标题左对齐时与 Y 轴 name 文字重叠
 * 3. 长主标题与顶部右侧图例重叠
 *
 * 在主题颜色注入前调用，确保布局先于颜色适配。
 */
function fixChartLayout(option: PlainObject): PlainObject {
  const fixed = { ...option };

  // ── Grid: 边距归一化 + 轴标签自适应 ──
  // ECharts 默认 left/right 各 10%、bottom 60px 对 320px 容器过于宽敞。
  // 用紧凑默认值替换，同时 containLabel 保证轴标签不会被裁剪。
  let grid: PlainObject = fixed.grid
    ? { ...(fixed.grid as PlainObject) }
    : {};

  if (grid.containLabel === undefined) {
    grid.containLabel = true;
  }

  // 四边归一化：只压制过大值，合理的 LLM 设定（如 left: 55）原样保留
  const hasSubtitle =
    fixed.title &&
    typeof fixed.title === 'object' &&
    typeof (fixed.title as PlainObject).subtext === 'string';

  const topDefault = hasSubtitle ? 72 : 50;
  grid.top = normalizeGridSide(grid.top, topDefault, 90, 18);
  grid.left = normalizeGridSide(grid.left, 50, 80, 12);
  grid.right = normalizeGridSide(grid.right, 16, 60, 10);
  grid.bottom = normalizeGridSide(grid.bottom, 36, 60, 15);

  // ── Title 布局修正 ──
  if (fixed.title && typeof fixed.title === 'object') {
    const title = { ...(fixed.title as PlainObject) };
    const titleSubtext = title.subtext as string | undefined;
    const titleText = title.text as string | undefined;

    // FIX 1: 副标题左对齐 + Y 轴存在 name → 将标题右移以避让 Y 轴 name 区域
    if (titleSubtext && typeof titleSubtext === 'string') {
      const titleLeft = title.left;
      const isLeftish =
        titleLeft === undefined ||
        titleLeft === 'left' ||
        (typeof titleLeft === 'number' && titleLeft < 40);

      if (isLeftish && yAxisHasName(fixed.yAxis)) {
        // 标题 left 对齐到归一化后的 grid.left，避让 Y 轴 name
        title.left = typeof grid.left === 'number' ? grid.left : 50;
      }
    }

    // FIX 2: 长标题 + 顶部右侧图例 → 截断标题
    if (titleText && typeof titleText === 'string' && titleText.length > 15) {
      if (legendAtTopRight(fixed.legend)) {
        title.textStyle = {
          ...(title.textStyle as PlainObject || {}),
          width: 220,
          overflow: 'truncate',
        };
      }
    }

    fixed.title = title;
  }

  // ── Legend 间距 ──
  if (fixed.legend && typeof fixed.legend === 'object') {
    const legend = { ...(fixed.legend as PlainObject) };
    if (hasSubtitle && (legend.top === undefined || legend.top === 0)) {
      legend.top = 45;
    }
    fixed.legend = legend;
  }

  fixed.grid = grid;
  return fixed;
}

/** Patch a single axis object with theme-aware colors */
function patchSingleAxis(args: AxisPatchArgs): PlainObject {
  const { axis, labelColor, lineColor, splitLineColor } = args;
  const patched = { ...axis };
  if (patched.axisLabel && typeof patched.axisLabel === 'object') {
    patched.axisLabel = { ...(patched.axisLabel as PlainObject), color: labelColor };
  }
  if (patched.axisLine && typeof patched.axisLine === 'object') {
    const line = patched.axisLine as PlainObject;
    patched.axisLine = {
      ...line,
      lineStyle: { ...(line.lineStyle as PlainObject || {}), color: lineColor },
    };
  }
  // Y-axis splitLine
  if (patched.splitLine && typeof patched.splitLine === 'object') {
    const sl = patched.splitLine as PlainObject;
    patched.splitLine = {
      ...sl,
      lineStyle: { ...(sl.lineStyle as PlainObject || {}), color: splitLineColor },
    };
  }
  return patched;
}

/**
 * 将 LLM 生成的 ECharts option 根据当前主题做完整颜色注入。
 * 无论深色/浅色，始终由前端统一管理所有视觉属性。
 */
function adaptChartOption(option: Record<string, unknown>, theme: 'dark' | 'light'): Record<string, unknown> {
  const dataColors = theme === 'dark' ? DARK_DATA_COLORS : LIGHT_DATA_COLORS;
  const textPrimary = theme === 'dark' ? DARK_TEXT_PRIMARY : LIGHT_TEXT_PRIMARY;
  const textSecondary = theme === 'dark' ? DARK_TEXT_SECONDARY : LIGHT_TEXT_SECONDARY;
  const border = theme === 'dark' ? DARK_BORDER : LIGHT_BORDER;
  const tooltipBg = theme === 'dark' ? DARK_TOOLTIP_BG : LIGHT_TOOLTIP_BG;

  // 先修布局冲突，再注入主题颜色
  const adapted: PlainObject = fixChartLayout(option as PlainObject);

  // 1. 数据系列颜色 — 始终注入，覆盖 LLM 可能指定的颜色
  adapted.color = dataColors;

  // 2. Title
  if (adapted.title && typeof adapted.title === 'object') {
    const t = adapted.title as PlainObject;
    adapted.title = { ...t, textStyle: { ...(t.textStyle as PlainObject || {}), color: textPrimary } };
  }

  // 3. Legend
  if (adapted.legend && typeof adapted.legend === 'object') {
    const l = adapted.legend as PlainObject;
    adapted.legend = { ...l, textStyle: { ...(l.textStyle as PlainObject || {}), color: textSecondary } };
  }

  // 4. Tooltip
  if (adapted.tooltip && typeof adapted.tooltip === 'object') {
    const tt = adapted.tooltip as PlainObject;
    adapted.tooltip = {
      ...tt,
      backgroundColor: tooltipBg,
      borderColor: border,
      textStyle: { ...(tt.textStyle as PlainObject || {}), color: textPrimary },
    };
  }

  // 5. xAxis — 支持单对象和数组
  if (adapted.xAxis) {
    const axisArgs = { labelColor: textSecondary, lineColor: border, splitLineColor: border };
    if (Array.isArray(adapted.xAxis)) {
      adapted.xAxis = adapted.xAxis.map(a => patchSingleAxis({ axis: a as PlainObject, ...axisArgs }));
    } else if (typeof adapted.xAxis === 'object') {
      adapted.xAxis = patchSingleAxis({ axis: adapted.xAxis as PlainObject, ...axisArgs });
    }
  }

  // 6. yAxis — 支持单对象和数组
  if (adapted.yAxis) {
    const axisArgs = { labelColor: textSecondary, lineColor: border, splitLineColor: border };
    if (Array.isArray(adapted.yAxis)) {
      adapted.yAxis = adapted.yAxis.map(a => patchSingleAxis({ axis: a as PlainObject, ...axisArgs }));
    } else if (typeof adapted.yAxis === 'object') {
      adapted.yAxis = patchSingleAxis({ axis: adapted.yAxis as PlainObject, ...axisArgs });
    }
  }

  return adapted;
}

export function ChartWidget({ chart, compact = false }: ChartWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!containerRef.current) return;

    if (!instanceRef.current) {
      instanceRef.current = echarts.init(containerRef.current, undefined, {
        backgroundColor: 'transparent',
      } as any);
    }

    const adaptedOption = adaptChartOption(chart.option, theme);

    const option = {
      ...adaptedOption,
      animationDuration: 800,
    };

    instanceRef.current.setOption(option, true);

    const handleResize = () => instanceRef.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [chart, theme]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  return (
    <div className="mb-4 bg-[var(--color-surface)]/30 border border-[var(--color-border)]/40 rounded-xl p-4 animate-slide-up">
      <div ref={containerRef} style={{ width: '100%', height: compact ? '140px' : '320px' }} />
    </div>
  );
}