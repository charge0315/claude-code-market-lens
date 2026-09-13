'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Sparkline } from '@/components/ui/Sparkline';
import { fetchMarketSnapshot, type MarketSnapshot } from '@/lib/api/market';
import './dashboard.css';

// ダッシュボード上部の指数ティッカー行（🆕 P13、参照デザイン準拠）。
// 主要指数（日経平均/TOPIX/S&P500/USD-JPY/日経VI）+ 市況ステータス + 更新時刻。
// 取得失敗・全指数が解決できない場合は静かに非表示にする（フェイルソフト、
// ダッシュボード全体の表示を妨げない）。

function changeColor(change: number): string {
  if (change > 0) return 'var(--color-gain)';
  if (change < 0) return 'var(--color-loss)';
  return 'var(--color-flat)';
}

function formatSigned(value: number, digits: number): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
}

export function MarketTickerBar(): ReactNode {
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);

  useEffect(() => {
    fetchMarketSnapshot()
      .then(setSnapshot)
      .catch(() => setSnapshot(null));
  }, []);

  if (!snapshot || snapshot.indices.length === 0) return null;

  return (
    <div className="market-ticker-bar">
      <div className="market-ticker-status">
        <span className="market-ticker-badge">{snapshot.market_status}</span>
        <span className="market-ticker-updated">更新 {snapshot.updated_at.slice(0, 16).replace('T', ' ')}</span>
      </div>
      <div className="market-ticker-tiles">
        {snapshot.indices.map((idx) => (
          <div key={idx.label} className="market-ticker-tile">
            <div className="market-ticker-tile-text">
              <span className="market-ticker-label">{idx.label}</span>
              <span className="market-ticker-value">
                {idx.value.toLocaleString('ja-JP', { maximumFractionDigits: 2 })}
              </span>
              <span className="market-ticker-change" style={{ color: changeColor(idx.change) }}>
                {formatSigned(idx.change, 2)}（{formatSigned(idx.change_pct, 2)}%）
              </span>
            </div>
            <Sparkline values={idx.spark} color={changeColor(idx.change)} />
          </div>
        ))}
      </div>
    </div>
  );
}
