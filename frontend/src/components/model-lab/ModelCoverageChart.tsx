'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchModelCoverage, type ModelCoverage } from '@/lib/api/registry';
import './model-lab.css';

// 学習カバレッジ（🆕 P15、🔧 コンパクト化）: モデルタイプごとに東証全銘柄の何%を
// 学習済み・champion採用済みかを、小さいリング（ドーナツ）で表示する。
// 1枚のグラフに全モデルタイプを詰め込む棒グラフではなく、モデルタイプごとに独立した
// 小さいカードにすることで、1行に複数並べやすく・「かんたん」タブにも収まるサイズにする。

const RING_SIZE = 88;
const RING_STROKE = 9;
const RADIUS = (RING_SIZE - RING_STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface CoverageRow {
  modelType: string;
  label: string;
  universeSize: number;
  trainedCount: number;
  championCount: number;
  learnedPct: number;
  /** champion 採用分を除いた「学習済みだが未採用」の割合（リングの内訳用）。 */
  trainedOnlyPct: number;
  championPct: number;
}

function toRows(coverage: ModelCoverage[]): CoverageRow[] {
  return coverage.map((c) => {
    const learnedPct = c.universe_size > 0 ? (c.trained_count / c.universe_size) * 100 : 0;
    const championPct = c.universe_size > 0 ? (c.champion_count / c.universe_size) * 100 : 0;
    return {
      modelType: c.model_type,
      label: c.label,
      universeSize: c.universe_size,
      trainedCount: c.trained_count,
      championCount: c.champion_count,
      learnedPct,
      trainedOnlyPct: Math.max(0, learnedPct - championPct),
      championPct,
    };
  });
}

function CoverageRing({ row }: { row: CoverageRow }): ReactNode {
  const trainedOnlyLen = (row.trainedOnlyPct / 100) * CIRCUMFERENCE;
  const championLen = (row.championPct / 100) * CIRCUMFERENCE;
  const center = RING_SIZE / 2;

  return (
    <svg
      width={RING_SIZE}
      height={RING_SIZE}
      viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
      role="img"
      aria-label={`${row.label}: 学習済み ${row.trainedCount}/${row.universeSize}銘柄（${row.learnedPct.toFixed(0)}%）、うち champion採用 ${row.championCount}銘柄（${row.championPct.toFixed(1)}%）`}
    >
      <circle cx={center} cy={center} r={RADIUS} fill="none" stroke="var(--color-border)" strokeWidth={RING_STROKE} />
      {trainedOnlyLen > 0 && (
        <circle
          cx={center}
          cy={center}
          r={RADIUS}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth={RING_STROKE}
          strokeDasharray={`${trainedOnlyLen} ${CIRCUMFERENCE - trainedOnlyLen}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
      )}
      {championLen > 0 && (
        <circle
          cx={center}
          cy={center}
          r={RADIUS}
          fill="none"
          stroke="var(--color-term-yellow)"
          strokeWidth={RING_STROKE}
          strokeDasharray={`${championLen} ${CIRCUMFERENCE - championLen}`}
          strokeDashoffset={-trainedOnlyLen}
          transform={`rotate(-90 ${center} ${center})`}
        />
      )}
      <text x={center} y={center} textAnchor="middle" dominantBaseline="central" className="coverage-ring-text">
        {row.learnedPct.toFixed(0)}%
      </text>
    </svg>
  );
}

export function ModelCoverageChart(): ReactNode {
  const [coverage, setCoverage] = useState<ModelCoverage[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchModelCoverage()
      .then(setCoverage)
      .catch(() => setError('学習カバレッジの取得に失敗しました'));
  }, []);

  const rows = toRows(coverage);
  const hasAnyTraining = rows.some((r) => r.trainedCount > 0);

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}

      {!error && !hasAnyTraining ? (
        <p className="signal-queue-empty">データがありません（銘柄別モデルの学習実行後に表示されます）</p>
      ) : (
        !error && (
          <>
            <div className="coverage-legend">
              <span className="coverage-legend-item">
                <i className="coverage-legend-swatch" style={{ background: 'var(--color-term-yellow)' }} />
                champion採用
              </span>
              <span className="coverage-legend-item">
                <i className="coverage-legend-swatch" style={{ background: 'var(--color-accent)' }} />
                学習済み（champion未満）
              </span>
              <span className="coverage-legend-item">
                <i className="coverage-legend-swatch" style={{ background: 'var(--color-border)' }} />
                未学習
              </span>
            </div>
            <div className="coverage-grid">
              {rows.map((row) => (
                <div key={row.modelType} className="coverage-card">
                  <CoverageRing row={row} />
                  <p className="coverage-card-label">{row.label}</p>
                  <p className="coverage-card-detail">
                    学習済み {row.trainedCount}/{row.universeSize}
                  </p>
                  <p className="coverage-card-detail">champion {row.championCount}銘柄</p>
                </div>
              ))}
            </div>
          </>
        )
      )}
    </div>
  );
}
