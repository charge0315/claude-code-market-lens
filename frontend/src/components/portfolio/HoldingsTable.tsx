import type { ReactNode } from 'react';
import type { PortfolioHolding } from '@/lib/api/portfolio';

// 保有銘柄一覧。評価損益・騰落率は国内証券標準（上げ=赤/下げ=緑）で色分けする。
// 🆕 P26: 行ごとに「売る」「削除」操作を追加。
// 🔧 Organic デザイン導入: テーブル行 → 銘柄カードのグリッドに構造変更。

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

export function HoldingsTable({
  holdings,
  onSell,
  onDelete,
}: {
  holdings: ReadonlyArray<PortfolioHolding>;
  onSell: (holding: PortfolioHolding) => void;
  onDelete: (holding: PortfolioHolding) => void;
}): ReactNode {
  if (holdings.length === 0) {
    return <p className="data-table-empty">保有銘柄がありません</p>;
  }

  return (
    <ul className="holdings-grid" aria-label="保有銘柄一覧（リアルタイム時価評価）">
      {holdings.map((h) => (
        <li key={h.holding_id} className="holding-card">
          <div className="holding-card-header">
            <span>
              {h.symbol} {h.company_name ?? ''}
            </span>
            <span className="tag-outline">{h.quantity}株</span>
          </div>
          <div className="holding-card-grid">
            <div>
              <span className="holding-card-label">取得単価</span>
              <span className="holding-card-value">{formatYen(h.avg_cost)}</span>
            </div>
            <div>
              <span className="holding-card-label">現在値</span>
              <span className="holding-card-value">{formatYen(h.current_price)}</span>
            </div>
            <div>
              <span className="holding-card-label">評価額</span>
              <span className="holding-card-value">{formatYen(h.current_value)}</span>
            </div>
            <div>
              <span className="holding-card-label">評価損益</span>
              <span className="holding-card-value" style={{ color: directionColor(h.gain_loss) }}>
                {formatYen(h.gain_loss)}
              </span>
            </div>
            <div>
              <span className="holding-card-label">騰落率</span>
              <span className="holding-card-value" style={{ color: directionColor(h.return_pct) }}>
                {formatPct(h.return_pct)}
              </span>
            </div>
          </div>
          <div className="holding-card-footer">
            <span className="holding-card-acquired">取得日 {h.acquired_at}</span>
            <span className="holding-row-actions">
              <button type="button" onClick={() => onSell(h)}>
                売る
              </button>
              <button type="button" onClick={() => onDelete(h)}>
                削除
              </button>
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
