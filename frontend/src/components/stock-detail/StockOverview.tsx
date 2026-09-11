'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchRecentRuns, type RunSummary } from '@/lib/api/inference';
import { fetchPickDetail, type PickDetail } from '@/lib/api/picks';
import { PriceChart } from './PriceChart';
import { SubScorePanel } from './SubScorePanel';
import './stock-detail.css';

// 直近の推論実行から銘柄を1件選び、チャート + 4分析内訳を表示する（AI 思考トレースの
// 対象と揃えるため `PipelineTraceViewer` と同じ「直近の実行」基準を使うが、独立して
// 自己完結させている — トレース側の run ピッカーで別の履歴を選んでも、ここは常に
// 最新の1件を参照する設計）。

export function StockOverview(): ReactNode {
  const [run, setRun] = useState<RunSummary | null | undefined>(undefined);
  const [pick, setPick] = useState<PickDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRecentRuns({ limit: 1 })
      .then((runs) => setRun(runs[0] ?? null))
      .catch(() => setError('直近の実行の取得に失敗しました'));
  }, []);

  useEffect(() => {
    if (!run?.pick_id) return;
    fetchPickDetail(run.pick_id)
      .then(setPick)
      .catch(() => undefined);
  }, [run]);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (run === undefined) return null;
  if (run === null) return <p className="signal-queue-empty">まだ推論実行がありません（ピック生成後に表示されます）</p>;

  return (
    <div className="stock-overview">
      <p className="stock-overview-symbol">{run.symbol}</p>
      <PriceChart symbol={run.symbol} />
      {pick && <SubScorePanel pick={pick} />}
    </div>
  );
}
