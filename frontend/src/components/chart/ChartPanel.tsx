'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { PriceChart } from '@/components/stock-detail/PriceChart';
import { directionColor, formatYen } from '@/components/dashboard/pickDisplay';
import { fetchQuote, type Quote } from '@/lib/api/stock';
import './chart.css';

// 銘柄検索→即チャート、を主目的にした軽量パネル（movement-chart 移植、🆕）。
// 銘柄詳細画面の `StockOverview` は AI 推論実行（run）が存在する銘柄しかチャートを
// 表示しない制約があるため、AI ピック対象外の銘柄も含めて任意の銘柄を素早く見たい
// 場合の代替として新設した（CLAUDE.md の主要画面「チャート」）。

export function ChartPanel({ symbol }: { symbol: string | null }): ReactNode {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    fetchQuote(symbol)
      .then((q) => {
        setQuote(q);
        setError(null);
      })
      .catch(() => setError('現在値の取得に失敗しました'));
  }, [symbol]);

  if (!symbol) {
    return <p className="signal-queue-empty">銘柄を検索するか、一覧から選択してください</p>;
  }

  return (
    <div className="chart-panel">
      <div className="chart-panel-header">
        <span className="chart-panel-symbol">{symbol}</span>
        {error && <p className="signal-queue-error">{error}</p>}
        {quote && quote.price !== null && (
          <span className="chart-panel-quote">
            <span className="chart-panel-price">{formatYen(quote.price)}</span>
            {quote.change_pct !== null && (
              <span
                className="chart-panel-change"
                style={{
                  color: directionColor(quote.change_pct > 0 ? 'bullish' : quote.change_pct < 0 ? 'bearish' : 'neutral'),
                }}
              >
                {quote.change_pct > 0 ? '+' : ''}
                {quote.change_pct.toFixed(2)}%
              </span>
            )}
          </span>
        )}
      </div>
      <PriceChart symbol={symbol} enableAdvancedControls />
    </div>
  );
}
