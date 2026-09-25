import type { ReactNode } from 'react';
import { directionColor } from '@/components/dashboard/pickDisplay';
import {
  RANGE_LABELS,
  summarizeTimeframes,
  TREND_DESCRIPTIONS,
  TREND_LABELS,
  type TimeframeInsight,
  type TimeframeSet,
  type TrendKind,
} from '@/lib/multiChartInsights';

// 🆕 マルチチャートの各パネル下と一覧下に「チャートから読み取れること」を表示する。
// 算出ロジックは `lib/multiChartInsights.ts`（ルールベース）。騰落色は国内証券標準
// （上昇=赤/下降=緑）の `directionColor` を経由させ、海外仕様の色を持ち込まない。

function trendColor(trend: TrendKind): string {
  if (trend === 'up') return directionColor('bullish');
  if (trend === 'down') return directionColor('bearish');
  return directionColor('neutral');
}

function formatPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function TimeframeInsightList({ insight }: { insight: TimeframeInsight }): ReactNode {
  const changeDirection = insight.changePct > 0 ? 'bullish' : insight.changePct < 0 ? 'bearish' : 'neutral';
  return (
    <dl className="multi-chart-insight">
      <dt>期間騰落</dt>
      <dd className="multi-chart-insight-num" style={{ color: directionColor(changeDirection) }}>
        {formatPct(insight.changePct)}
      </dd>
      <dt>流れ</dt>
      <dd title={TREND_DESCRIPTIONS[insight.trend]} style={{ color: trendColor(insight.trend) }}>
        {TREND_LABELS[insight.trend]}
      </dd>
      <dt>位置</dt>
      <dd>
        {RANGE_LABELS[insight.rangePosition]}
        <span className="multi-chart-insight-num">（{Math.round(insight.rangePct)}%）</span>
      </dd>
    </dl>
  );
}

export function MultiChartInsightSummary({ timeframes }: { timeframes: TimeframeSet }): ReactNode {
  const lines = summarizeTimeframes(timeframes);
  if (lines.length === 0) return null;
  return (
    <section className="multi-chart-summary" aria-labelledby="multi-chart-summary-heading">
      <h3 id="multi-chart-summary-heading" className="multi-chart-summary-heading">
        チャートから読み取れること
      </h3>
      <ul className="multi-chart-summary-list">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="multi-chart-summary-note">
        「流れ」は各足の20本移動平均と終値の位置・平均線の向き、「位置」は表示期間の安値〜高値レンジ内での直近終値の位置（0%=安値、100%=高値）から機械的に算出した値動きの要約です。売買を推奨するものではありません。
      </p>
    </section>
  );
}
