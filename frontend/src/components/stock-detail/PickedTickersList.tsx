'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { fetchGeminiPicks, fetchPicks, type GeminiPickSummary, type PickSummary } from '@/lib/api/picks';
import './stock-detail.css';

// ピックされた銘柄の一覧（🆕 Claude/Gemini 別々に選択可能、P25 の続き）。
// クリックで `?symbol=` を切り替え、下のチャート・4分析内訳・AI推論トレースを
// その銘柄のものに切り替える。同一銘柄が両エンジンでピックされていれば両方表示する。

type Engine = 'claude' | 'gemini';

interface TickerEntry {
  symbol: string;
  companyName: string | null;
  engine: Engine;
}

function dedupeBySymbolKeepingLatest<T extends { symbol: string }>(picks: T[]): T[] {
  const bySymbol = new Map<string, T>();
  // fetchPicks/fetchGeminiPicks は新しい順で返すため、先に見つかった方（＝新しい方）を残す。
  for (const p of picks) {
    if (!bySymbol.has(p.symbol)) bySymbol.set(p.symbol, p);
  }
  return [...bySymbol.values()];
}

export function PickedTickersList({ selectedSymbol }: { selectedSymbol: string | null }): ReactNode {
  const [entries, setEntries] = useState<TickerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchPicks('mid_term', { limit: 50 }),
      fetchPicks('short_term', { limit: 50 }),
      fetchGeminiPicks('mid_term', { limit: 50 }),
      fetchGeminiPicks('short_term', { limit: 50 }),
    ])
      .then(([claudeMid, claudeShort, geminiMid, geminiShort]) => {
        const claude = dedupeBySymbolKeepingLatest<PickSummary>([...claudeMid, ...claudeShort]).map(
          (p): TickerEntry => ({ symbol: p.symbol, companyName: p.company_name, engine: 'claude' }),
        );
        const gemini = dedupeBySymbolKeepingLatest<GeminiPickSummary>([...geminiMid, ...geminiShort]).map(
          (p): TickerEntry => ({ symbol: p.symbol, companyName: p.company_name, engine: 'gemini' }),
        );
        setEntries([...claude, ...gemini]);
      })
      .catch(() => setError('ピック銘柄一覧の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (entries.length === 0) return <p className="signal-queue-empty">ピックされた銘柄はまだありません</p>;

  return (
    <ul className="picked-tickers-list" aria-label="ピックされた銘柄一覧">
      {entries.map((e) => (
        <li key={`${e.engine}-${e.symbol}`}>
          <Link
            href={`/stock-detail?symbol=${encodeURIComponent(e.symbol)}`}
            className={e.symbol === selectedSymbol ? 'is-active' : undefined}
            aria-current={e.symbol === selectedSymbol ? 'true' : undefined}
          >
            <span className="picked-ticker-engine-badge">{e.engine === 'claude' ? 'Claude' : 'Gemini'}</span>
            {e.symbol}
            {e.companyName && `（${e.companyName}）`}
          </Link>
        </li>
      ))}
    </ul>
  );
}
