import { forwardRef } from 'react';

// 日次noteドラフトへ挿入するための、ラベル付き折れ線チャート（🆕）。
// `ui/Sparkline.tsx`（56x20のUI装飾用）とは別に、記事に貼り付けても読める大きさ・軸ラベル付きで
// 用意する。`lib/exportChartImage.ts` でPNG化してダウンロードする際、SVGはページのCSSカスタム
// プロパティ（var(--color-*)）へアクセスできないため、色は実際の16進値で固定する
// （`pickDisplay.tsx` の --color-gain/--color-loss と同じ値、国内証券基準で上昇=赤・下落=緑）。

const WIDTH = 560;
const HEIGHT = 220;
const PADDING = { top: 24, right: 16, bottom: 28, left: 16 };

const GAIN_HEX = '#b32424';
const LOSS_HEX = '#1f6b3a';
const FLAT_HEX = '#6b675f';
const BG_HEX = '#f5ead8';
const TEXT_HEX = '#201e1d';
const MUTED_HEX = '#5c584f';

export function noteChartColor(values: readonly number[]): string {
  if (values.length < 2) return FLAT_HEX;
  const delta = values[values.length - 1] - values[0];
  if (delta > 0) return GAIN_HEX;
  if (delta < 0) return LOSS_HEX;
  return FLAT_HEX;
}

export interface NoteChartProps {
  title: string;
  values: readonly number[];
}

export const NoteChart = forwardRef<SVGSVGElement, NoteChartProps>(function NoteChart({ title, values }, ref) {
  if (values.length < 2) return null;

  const color = noteChartColor(values);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const chartWidth = WIDTH - PADDING.left - PADDING.right;
  const chartHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const points = values
    .map((v, i) => {
      const x = PADDING.left + (i / (values.length - 1)) * chartWidth;
      const y = PADDING.top + chartHeight - ((v - min) / span) * chartHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      ref={ref}
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`${title}の値動きチャート（直近${values.length}日分）`}
    >
      <rect x={0} y={0} width={WIDTH} height={HEIGHT} fill={BG_HEX} />
      <text x={PADDING.left} y={16} fontSize={14} fill={TEXT_HEX} fontFamily="sans-serif">
        {title}
      </text>
      <text x={WIDTH - PADDING.right} y={PADDING.top + 4} fontSize={11} fill={MUTED_HEX} textAnchor="end" fontFamily="sans-serif">
        {max.toLocaleString('ja-JP')}
      </text>
      <text x={WIDTH - PADDING.right} y={HEIGHT - PADDING.bottom} fontSize={11} fill={MUTED_HEX} textAnchor="end" fontFamily="sans-serif">
        {min.toLocaleString('ja-JP')}
      </text>
      <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <text x={PADDING.left} y={HEIGHT - 8} fontSize={10} fill={MUTED_HEX} fontFamily="sans-serif">
        直近{values.length}日分の終値推移（参考情報）
      </text>
    </svg>
  );
});
