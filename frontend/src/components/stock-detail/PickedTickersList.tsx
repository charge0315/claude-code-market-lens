'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { fetchPicks, fetchShadowPicks, type PickSummary, type ShadowPickSummary } from '@/lib/api/picks';
import { fetchPortfolio } from '@/lib/api/portfolio';
import { challengerProviderLabel, useOfficialProviderLabel } from '@/lib/llmProviderLabels';
import { todayJst } from '@/lib/jstDate';
import './stock-detail.css';

// ピックされた銘柄の一覧（公式/シャドウを別々に選択可能）。
// クリックで `?symbol=` を切り替え、下のチャート・4分析内訳・AI推論トレースを
// その銘柄のものに切り替える。同一銘柄が両エンジンでピックされていれば両方表示する。
// 表示対象は「当日ピックされた銘柄」と「ポートフォリオ登録済み銘柄」のみに絞る
// （過去分の全ピックを出すと一覧が肥大化し、当日の判断材料として使いづらいため）。

type Engine = 'official' | 'shadow' | 'portfolio';

interface TickerEntry {
  symbol: string;
  companyName: string | null;
  engine: Engine;
  // engine === 'shadow' の場合のみ設定（バッジのモデル名表示用、"<provider>:<model>" 形式）。
  challengerVersion?: string;
}

function dedupeBySymbolKeepingLatest<T extends { symbol: string }>(picks: T[]): T[] {
  const bySymbol = new Map<string, T>();
  // fetchPicks/fetchShadowPicks は新しい順で返すため、先に見つかった方（＝新しい方）を残す。
  for (const p of picks) {
    if (!bySymbol.has(p.symbol)) bySymbol.set(p.symbol, p);
  }
  return [...bySymbol.values()];
}

export function PickedTickersList({ selectedSymbol }: { selectedSymbol: string | null }): ReactNode {
  const [entries, setEntries] = useState<TickerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const officialLabel = useOfficialProviderLabel('stock_pick');

  useEffect(() => {
    const today = todayJst();
    Promise.all([
      fetchPicks('mid_term', { date: today, limit: 50 }),
      fetchPicks('short_term', { date: today, limit: 50 }),
      fetchShadowPicks('mid_term', { date: today, limit: 50 }),
      fetchShadowPicks('short_term', { date: today, limit: 50 }),
      fetchPortfolio(),
    ])
      .then(([officialMid, officialShort, shadowMid, shadowShort, portfolio]) => {
        const official = dedupeBySymbolKeepingLatest<PickSummary>([...officialMid, ...officialShort]).map(
          (p): TickerEntry => ({ symbol: p.symbol, companyName: p.company_name, engine: 'official' }),
        );
        const shadow = dedupeBySymbolKeepingLatest<ShadowPickSummary>([...shadowMid, ...shadowShort]).map(
          (p): TickerEntry => ({
            symbol: p.symbol,
            companyName: p.company_name,
            engine: 'shadow',
            challengerVersion: p.challenger_version,
          }),
        );
        // 当日ピック済み（公式/シャドウどちらか）の銘柄は保有欄で重複表示しない。
        const pickedSymbols = new Set([...official, ...shadow].map((e) => e.symbol));
        const holdings = dedupeBySymbolKeepingLatest(portfolio.holdings)
          .filter((h) => !pickedSymbols.has(h.symbol))
          .map((h): TickerEntry => ({ symbol: h.symbol, companyName: h.company_name, engine: 'portfolio' }));
        setEntries([...official, ...shadow, ...holdings]);
      })
      .catch(() => setError('ピック銘柄一覧の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (entries.length === 0) return <p className="signal-queue-empty">本日のピック・保有銘柄はまだありません</p>;

  return (
    <ul className="picked-tickers-list" aria-label="本日のピック・保有銘柄一覧">
      {entries.map((e) => (
        <li key={`${e.engine}-${e.symbol}`}>
          <Link
            href={`/stock-detail?symbol=${encodeURIComponent(e.symbol)}`}
            className={e.symbol === selectedSymbol ? 'is-active' : undefined}
            aria-current={e.symbol === selectedSymbol ? 'true' : undefined}
          >
            <span className="picked-ticker-engine-badge">
              {e.engine === 'official'
                ? officialLabel
                : e.engine === 'shadow'
                  ? challengerProviderLabel(e.challengerVersion ?? '')
                  : '保有'}
            </span>
            {e.symbol}
            {e.companyName && `（${e.companyName}）`}
          </Link>
        </li>
      ))}
    </ul>
  );
}
