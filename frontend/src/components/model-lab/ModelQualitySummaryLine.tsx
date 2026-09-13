'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchQualityDistribution, type QualityDistribution } from '@/lib/api/registry';
import './model-lab.css';

// 「かんたん」タブ向けの1行サマリー（ユーザー指示）。詳細な分布ヒストグラム（モデル
// タイプ・指標を切り替えられる `ModelQualityChart`）は「詳細」タブに残し、初心者向けには
// 全モデルタイプ合算の平均値だけを1行で見せる。

function average(values: number[]): number | null {
  return values.length === 0 ? null : values.reduce((sum, v) => sum + v, 0) / values.length;
}

export function ModelQualitySummaryLine(): ReactNode {
  const [distributions, setDistributions] = useState<QualityDistribution[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchQualityDistribution()
      .then(setDistributions)
      .catch(() => setError('モデル品質分布の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;

  const skillScores = distributions.flatMap((d) => d.skill_scores);
  const rmseScores = distributions.flatMap((d) => d.rmse_scores);
  const avgSkill = average(skillScores);
  const avgRmse = average(rmseScores);

  if (avgSkill === null || avgRmse === null) {
    return <p className="signal-queue-empty">まだ champion がありません（学習・品質ゲート通過後に表示されます）</p>;
  }

  return (
    <p className="model-lab-brier">
      champion採用 合計 {skillScores.length}銘柄・平均skillスコア {avgSkill.toFixed(3)}・平均RMSE {avgRmse.toFixed(3)}
    </p>
  );
}
