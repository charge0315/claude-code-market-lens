'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchTrainingTrend, type TrainingTrendPoint } from '@/lib/api/registry';
import './model-lab.css';

// 「かんたん」タブ向けの1行サマリー（ユーザー指示）。日別・モデルタイプ別の折れ線
// （`TrainingTrendChart`）は「詳細」タブに残し、初心者向けには直近7日の合計・1日平均・
// 最新日の件数だけを1行で見せる。

const DAYS = 7;

export function TrainingTrendSummaryLine(): ReactNode {
  const [points, setPoints] = useState<TrainingTrendPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTrainingTrend(DAYS)
      .then(setPoints)
      .catch(() => setError('学習推移の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (points.length === 0) {
    return <p className="signal-queue-empty">データがありません（銘柄別モデルの学習実行後に表示されます）</p>;
  }

  const byDate = new Map<string, number>();
  for (const p of points) {
    byDate.set(p.date, (byDate.get(p.date) ?? 0) + p.trained_count);
  }
  const dates = [...byDate.keys()].sort();
  const total = [...byDate.values()].reduce((sum, v) => sum + v, 0);
  const latestDate = dates[dates.length - 1];
  const latestCount = byDate.get(latestDate) ?? 0;

  return (
    <p className="model-lab-brier">
      直近{DAYS}日合計 {total}件学習・1日平均 {(total / dates.length).toFixed(1)}件・最新日（{latestDate}） {latestCount}件
    </p>
  );
}
