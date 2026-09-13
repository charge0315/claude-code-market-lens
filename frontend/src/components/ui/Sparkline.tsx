import type { ReactNode } from 'react';

// 依存ライブラリなしの軽量スパークライン（🆕 P23）。指数ティッカー・ピック一覧の
// 「直近の値動き」を小さく添えるための表示専用コンポーネント。誤差確認用途ではないため
// 軸・目盛りは持たない。

const WIDTH = 56;
const HEIGHT = 20;
const STROKE_WIDTH = 1.5;

export function Sparkline({ values, color }: { values: readonly number[]; color: string }): ReactNode {
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = STROKE_WIDTH;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (WIDTH - pad * 2) + pad;
      const y = HEIGHT - pad - ((v - min) / span) * (HEIGHT - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`直近の値動き（${values.length}日分）`}
      style={{ display: 'block', flexShrink: 0 }}
    >
      <polyline points={points} fill="none" stroke={color} strokeWidth={STROKE_WIDTH} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
