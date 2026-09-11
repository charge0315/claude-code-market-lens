'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchPicks, runPicks, type HorizonType, type PickSummary } from '@/lib/api/picks';
import './dashboard.css';

// 本日の AI 銘柄ピック（中長期 / 短期タブ）。確度順（backend が既にソート済み）で表示し、
// 3 値（買値 / 損切値 / 売値）と根拠プレビューを必ず併記する（CLAUDE.md）。

const DIRECTION_LABELS: Record<PickSummary['direction'], string> = {
  bullish: '強気',
  bearish: '弱気',
  neutral: '中立',
};

const BUCKET_LABELS: Record<PickSummary['confidence_bucket'], string> = {
  high: '高',
  mid: '中',
  low: '低',
};

function directionColor(direction: PickSummary['direction']): string {
  if (direction === 'bullish') return 'var(--color-gain)';
  if (direction === 'bearish') return 'var(--color-loss)';
  return 'var(--color-flat)';
}

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function truncate(text: string, max = 50): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

const COLUMNS: ReadonlyArray<Column<PickSummary>> = [
  { key: 'symbol', header: '銘柄' },
  {
    key: 'direction',
    header: '方向',
    render: (p) => <span style={{ color: directionColor(p.direction) }}>{DIRECTION_LABELS[p.direction]}</span>,
  },
  {
    key: 'confidence',
    header: '確度',
    numeric: true,
    render: (p) => `${p.confidence.toFixed(0)}（${BUCKET_LABELS[p.confidence_bucket]}）`,
  },
  { key: 'entry', header: '買値目安', numeric: true, render: (p) => formatYen(p.entry) },
  { key: 'stop', header: '損切値', numeric: true, render: (p) => formatYen(p.stop) },
  { key: 'target', header: '推奨売値', numeric: true, render: (p) => formatYen(p.target) },
  {
    key: 'rationale_text',
    header: '根拠プレビュー',
    render: (p) => <span title={p.rationale_text}>{truncate(p.rationale_text)}</span>,
  },
];

export function PicksBoard(): ReactNode {
  const [horizon, setHorizon] = useState<HorizonType>('mid_term');
  const [picks, setPicks] = useState<PickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback((h: HorizonType) => {
    fetchPicks(h, { limit: 50 })
      .then(setPicks)
      .catch(() => setError('ピック一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    load(horizon);
  }, [load, horizon]);

  const handleRun = (): void => {
    setRunning(true);
    setError(null);
    runPicks(horizon)
      .then((result) => {
        if (result.status !== 'ok' && result.message) {
          setError(result.message);
        }
        load(horizon);
      })
      .catch(() => setError('ピック生成に失敗しました'))
      .finally(() => setRunning(false));
  };

  return (
    <div className="picks-board">
      <div className="picks-board-toolbar">
        <div className="picks-board-tabs" role="group" aria-label="ホライズン">
          <button
            type="button"
            className={horizon === 'mid_term' ? 'is-active' : undefined}
            aria-pressed={horizon === 'mid_term'}
            onClick={() => setHorizon('mid_term')}
          >
            中長期
          </button>
          <button
            type="button"
            className={horizon === 'short_term' ? 'is-active' : undefined}
            aria-pressed={horizon === 'short_term'}
            onClick={() => setHorizon('short_term')}
          >
            短期
          </button>
        </div>
        <button type="button" onClick={handleRun} disabled={running}>
          {running ? '実行中…' : '手動更新'}
        </button>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      <DataTable
        caption="本日の AI 銘柄ピック（確度順）"
        columns={COLUMNS}
        rows={picks}
        rowKey={(p) => p.pick_id}
        emptyMessage="本日のピックはまだありません"
      />
    </div>
  );
}
