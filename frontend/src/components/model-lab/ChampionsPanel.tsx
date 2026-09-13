'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { applyPromotion, fetchChampions, fetchPromotions, type Champion, type Promotion } from '@/lib/api/registry';
import './model-lab.css';

// champion 一覧 + 昇格判定ログ。昇格の実適用は人手承認 API 経由のみ（CLAUDE.md、自動昇格は既定 OFF）。

const VERDICT_LABELS: Record<Promotion['verdict'], string> = {
  propose_promote: '昇格提案',
  hold: '見送り',
  reject: '却下',
};

const CHAMPION_COLUMNS: ReadonlyArray<Column<Champion>> = [
  { key: 'lane', header: '系統 (lane)' },
  { key: 'champion_version', header: 'champion バージョン' },
  { key: 'promoted_at', header: '昇格日時' },
  { key: 'promoted_by', header: '昇格経路' },
];

export function ChampionsPanel(): ReactNode {
  const [champions, setChampions] = useState<Champion[]>([]);
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);

  const loadPromotions = useCallback(() => {
    fetchPromotions({ limit: 50 })
      .then(setPromotions)
      .catch(() => setError('昇格判定ログの取得に失敗しました'));
  }, []);

  useEffect(() => {
    fetchChampions()
      .then(setChampions)
      .catch(() => setError('champion 一覧の取得に失敗しました'));
    loadPromotions();
  }, [loadPromotions]);

  const handleApply = (promotionId: string): void => {
    setApplyingId(promotionId);
    applyPromotion(promotionId)
      .then(() => {
        loadPromotions();
        fetchChampions().then(setChampions).catch(() => undefined);
      })
      .catch(() => setError('昇格の適用に失敗しました'))
      .finally(() => setApplyingId(null));
  };

  const promotionColumns: ReadonlyArray<Column<Promotion>> = [
    { key: 'lane', header: '系統' },
    { key: 'challenger_version', header: 'challenger' },
    { key: 'champion_version', header: '比較対象 champion', render: (p) => p.champion_version ?? '—' },
    { key: 'holdout_delta', header: 'holdout 差分', numeric: true, render: (p) => p.holdout_delta.toFixed(4) },
    { key: 'paper_perf_delta', header: 'ペーパー成績差分', numeric: true, render: (p) => p.paper_perf_delta.toFixed(4) },
    {
      key: 'verdict',
      header: '判定',
      render: (p) => {
        const tagClass =
          p.verdict === 'propose_promote' && p.applied
            ? 'ml-tag ml-tag-accent-2'
            : p.verdict === 'propose_promote'
              ? 'ml-tag ml-tag-accent'
              : 'ml-tag ml-tag-neutral';
        return <span className={tagClass}>{VERDICT_LABELS[p.verdict]}</span>;
      },
    },
    { key: 'evaluated_at', header: '評価日時' },
    {
      key: 'action',
      header: '操作',
      render: (p) =>
        p.verdict === 'propose_promote' && !p.applied ? (
          <button type="button" onClick={() => handleApply(p.promotion_id)} disabled={applyingId === p.promotion_id}>
            適用
          </button>
        ) : p.applied ? (
          <span className="model-lab-applied">適用済み</span>
        ) : (
          '—'
        ),
    },
  ];

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}

      <h3 className="model-lab-subheading">現行 champion</h3>
      <DataTable
        caption="系統別の現行 champion"
        columns={CHAMPION_COLUMNS}
        rows={champions}
        rowKey={(c) => c.lane}
        emptyMessage="champion がまだ登録されていません"
      />

      <h3 className="model-lab-subheading">昇格判定ログ</h3>
      <DataTable
        caption="challenger の昇格判定履歴"
        columns={promotionColumns}
        rows={promotions}
        rowKey={(p) => p.promotion_id}
        emptyMessage="昇格判定はまだありません"
      />
    </div>
  );
}
