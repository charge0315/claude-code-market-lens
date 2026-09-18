'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchPitCoverage, type PitCoverageStatus } from '@/lib/api/registry';
import './model-lab.css';

// 「かんたん」タブ向けの1行進捗表示（🆕 P29、ユーザー指示）。
// 詳細な内訳（グループ別バー・投入可否）は「詳細」タブの `PitCoveragePanel` に置き、
// 初心者向けにはファンダメンタル（Vault決算情報）の収集進捗のみを1行で見せる。

export function PitCoverageSummaryLine(): ReactNode {
  const [status, setStatus] = useState<PitCoverageStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPitCoverage()
      .then(setStatus)
      .catch(() => setError('PIT特徴量の収集進捗の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (!status) return null;

  const fundamental = status.groups.find((g) => g.group === 'pit_fundamental');
  if (!fundamental) return null;

  if (fundamental.ready) {
    return (
      <p className="model-lab-brier">
        Vaultの決算情報（{fundamental.collected_days}営業日分）は学習に使える状態です。
      </p>
    );
  }
  return (
    <p className="model-lab-brier">
      Vaultの決算情報を学習に使えるまであと{fundamental.remaining_days}営業日（現在{fundamental.collected_days}
      /{fundamental.min_coverage_days}営業日分を収集済み）。
    </p>
  );
}
