import type { ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import type { PortfolioHolding } from '@/lib/api/portfolio';

// 保有銘柄一覧。評価損益・騰落率は国内証券標準（上げ=赤/下げ=緑）で色分けする。

function formatYen(value: number | null): string {
  return value === null ? '—' : `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function formatPct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`;
}

function directionColor(value: number | null): string {
  if (value === null || value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

const COLUMNS: ReadonlyArray<Column<PortfolioHolding>> = [
  { key: 'symbol', header: '銘柄', render: (h) => `${h.symbol} ${h.company_name ?? ''}`.trim() },
  { key: 'quantity', header: '株数', numeric: true },
  { key: 'avg_cost', header: '平均取得単価', numeric: true, render: (h) => formatYen(h.avg_cost) },
  { key: 'current_price', header: '現在値', numeric: true, render: (h) => formatYen(h.current_price) },
  { key: 'current_value', header: '評価額', numeric: true, render: (h) => formatYen(h.current_value) },
  {
    key: 'gain_loss',
    header: '評価損益',
    numeric: true,
    render: (h) => <span style={{ color: directionColor(h.gain_loss) }}>{formatYen(h.gain_loss)}</span>,
  },
  {
    key: 'return_pct',
    header: '騰落率',
    numeric: true,
    render: (h) => <span style={{ color: directionColor(h.return_pct) }}>{formatPct(h.return_pct)}</span>,
  },
  { key: 'acquired_at', header: '取得日' },
];

export function HoldingsTable({ holdings }: { holdings: ReadonlyArray<PortfolioHolding> }): ReactNode {
  return (
    <DataTable
      caption="保有銘柄一覧（リアルタイム時価評価）"
      columns={COLUMNS}
      rows={holdings}
      rowKey={(h) => h.holding_id}
      emptyMessage="保有銘柄がありません"
    />
  );
}
