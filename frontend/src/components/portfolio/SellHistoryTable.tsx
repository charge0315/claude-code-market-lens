'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchSellHistory, type SellHistoryEntry } from '@/lib/api/portfolio';

// 保有銘柄の売却履歴一覧（🆕 P26）。

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function directionColor(value: number): string {
  if (value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

const COLUMNS: ReadonlyArray<Column<SellHistoryEntry>> = [
  { key: 'symbol', header: '銘柄', render: (h) => `${h.symbol}${h.company_name ? `（${h.company_name}）` : ''}` },
  { key: 'quantity', header: '売却株数', numeric: true },
  { key: 'avg_cost', header: '取得単価', numeric: true, render: (h) => formatYen(h.avg_cost) },
  { key: 'sell_price', header: '売却価格', numeric: true, render: (h) => formatYen(h.sell_price) },
  {
    key: 'realized_pnl',
    header: '実現損益',
    numeric: true,
    render: (h) => <span style={{ color: directionColor(h.realized_pnl) }}>{formatYen(h.realized_pnl)}</span>,
  },
  { key: 'sold_at', header: '売却日' },
  { key: 'note', header: 'メモ', render: (h) => h.note ?? '—' },
];

export function SellHistoryTable({ reloadKey }: { reloadKey: number }): ReactNode {
  const [history, setHistory] = useState<SellHistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSellHistory()
      .then(setHistory)
      .catch(() => setError('売却履歴の取得に失敗しました'));
  }, [reloadKey]);

  if (error) return <p className="signal-queue-error">{error}</p>;

  return (
    <DataTable
      caption="保有銘柄の売却履歴"
      columns={COLUMNS}
      rows={history}
      rowKey={(h) => h.sell_id}
      emptyMessage="売却履歴はまだありません"
    />
  );
}
