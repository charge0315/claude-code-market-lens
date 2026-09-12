'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchRecentRuns, type RunSummary } from '@/lib/api/inference';
import { fetchPickDetail, type PickDetail } from '@/lib/api/picks';
import { PriceChart } from './PriceChart';
import { SubScorePanel } from './SubScorePanel';
import './stock-detail.css';

// `symbol` 指定時はその銘柄の直近の実行を選ぶ。未指定（従来どおり）は直近の実行を選ぶ
// （AI 思考トレースの対象と揃えるため `PipelineTraceViewer` と同じ「直近の実行」基準を使うが、
// 独立して自己完結させている）。

export function StockOverview({ symbol }: { symbol?: string | null } = {}): ReactNode {
  const [run, setRun] = useState<RunSummary | null | undefined>(undefined);
  const [pick, setPick] = useState<PickDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRecentRuns({ limit: symbol ? 100 : 1 })
      .then((runs) => setRun((symbol ? runs.find((r) => r.symbol === symbol) : runs[0]) ?? null))
      .catch(() => setError('直近の実行の取得に失敗しました'));
  }, [symbol]);

  useEffect(() => {
    if (!run?.pick_id) return;
    fetchPickDetail(run.pick_id)
      .then(setPick)
      .catch(() => undefined);
  }, [run]);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (run === undefined) return null;
  if (run === null) {
    return (
      <p className="signal-queue-empty">
        {symbol ? `${symbol} の推論実行がまだありません` : 'まだ推論実行がありません（ピック生成後に表示されます）'}
      </p>
    );
  }

  return (
    <div className="stock-overview">
      <p className="stock-overview-symbol">{run.symbol}</p>
      <PriceChart symbol={run.symbol} />
      {pick && <SubScorePanel pick={pick} />}
    </div>
  );
}
