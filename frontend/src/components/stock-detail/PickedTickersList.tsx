'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { fetchPicks, type PickSummary } from '@/lib/api/picks';
import './stock-detail.css';

// ピックされた銘柄の一覧（中長期 + 短期を合算し、銘柄ごとに最新の1件へ重複排除）。
// クリックで `?symbol=` を切り替え、下のチャート・4分析内訳・AI推論トレースを
// その銘柄のものに切り替える。

function dedupeBySymbolKeepingLatest(picks: PickSummary[]): PickSummary[] {
  const bySymbol = new Map<string, PickSummary>();
  // fetchPicks は新しい順で返すため、先に見つかった方（＝新しい方）を残す。
  for (const p of picks) {
    if (!bySymbol.has(p.symbol)) bySymbol.set(p.symbol, p);
  }
  return [...bySymbol.values()];
}

export function PickedTickersList({ selectedSymbol }: { selectedSymbol: string | null }): ReactNode {
  const [tickers, setTickers] = useState<PickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchPicks('mid_term', { limit: 50 }), fetchPicks('short_term', { limit: 50 })])
      .then(([midTerm, shortTerm]) => {
        setTickers(dedupeBySymbolKeepingLatest([...midTerm, ...shortTerm]));
      })
      .catch(() => setError('ピック銘柄一覧の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (tickers.length === 0) return <p className="signal-queue-empty">ピックされた銘柄はまだありません</p>;

  return (
    <ul className="picked-tickers-list" aria-label="ピックされた銘柄一覧">
      {tickers.map((p) => (
        <li key={p.symbol}>
          <Link
            href={`/stock-detail?symbol=${encodeURIComponent(p.symbol)}`}
            className={p.symbol === selectedSymbol ? 'is-active' : undefined}
            aria-current={p.symbol === selectedSymbol ? 'true' : undefined}
          >
            {p.symbol}
            {p.company_name && `（${p.company_name}）`}
          </Link>
        </li>
      ))}
    </ul>
  );
}
