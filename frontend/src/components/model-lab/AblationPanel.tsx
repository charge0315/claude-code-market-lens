'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchAblations, type SourceAblationEntry } from '@/lib/api/registry';
import './model-lab.css';

// ソースアブレーション評価（🆕 P29）。四半期ごと、PIT由来の特徴量グループ（Vault決算情報 /
// ニュースセンチメント）を1つ除外して再学習し、held-out指標がどれだけ悪化したかを記録する
// （`metric_delta` = 除外時 − 全部入り）。負の値ほど「その情報源が精度に貢献している」ことを
// 意味する — Vaultを足して本当に良くなったかを判定する唯一の客観的材料。

const SOURCE_LABELS: Record<string, string> = {
  pit_fundamental: 'ファンダメンタル（Vault決算情報）',
  pit_sentiment_keyword: 'ニュースセンチメント（キーワード）',
  pit_sentiment_llm: 'ニュースセンチメント（LLM）',
};

const METRIC_LABELS: Record<string, string> = {
  auc: 'AUC',
  brier_skill: 'Brierスキル',
  decile_spread: '十分位スプレッド',
};

const COLUMNS: ReadonlyArray<Column<SourceAblationEntry>> = [
  { key: 'quarter', header: '四半期' },
  { key: 'excluded_source', header: '除外した情報源', render: (r) => SOURCE_LABELS[r.excluded_source] ?? r.excluded_source },
  { key: 'metric_name', header: '指標', render: (r) => METRIC_LABELS[r.metric_name] ?? r.metric_name },
  {
    key: 'metric_delta',
    header: '差分（除外時−全部入り）',
    numeric: true,
    render: (r) => (
      <span style={{ color: r.metric_delta < 0 ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}>
        {r.metric_delta > 0 ? '+' : ''}
        {r.metric_delta.toFixed(4)}
      </span>
    ),
  },
  { key: 'sample_n', header: '検証サンプル数', numeric: true },
  { key: 'computed_at', header: '評価日時' },
];

export function AblationPanel(): ReactNode {
  const [rows, setRows] = useState<SourceAblationEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAblations()
      .then(setRows)
      .catch(() => setError('ソースアブレーション評価の取得に失敗しました'));
  }, []);

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}
      <p className="model-lab-as-of" style={{ marginTop: 0 }}>
        差分がマイナスであるほど、その情報源を除外すると精度が悪化した（＝その情報源が精度に
        貢献している）ことを意味します。四半期ごとに自動評価され、PIT特徴量の収集が
        `PIT_MIN_COVERAGE_DAYS` に満たないグループは評価対象外です。
      </p>
      <DataTable
        caption="ソースアブレーション評価履歴"
        columns={COLUMNS}
        rows={rows}
        rowKey={(r) => r.ablation_id}
        emptyMessage="アブレーション評価はまだありません（PIT特徴量の収集が進み次第、四半期ごとに自動評価されます）"
      />
    </div>
  );
}
