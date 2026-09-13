'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchGeminiPicks, fetchPicks, type GeminiPickSummary, type PickSummary } from '@/lib/api/picks';
import { todayJst } from '@/lib/jstDate';
import './portfolio.css';

// 銘柄検索と並ぶもう一つの追加経路: 本日の AI ピック（Claude/Gemini 両方）から選んで
// そのまま買い注文（保有追加）ポップアップを開けるようにする（ユーザー指示）。

export type AiPickEngine = 'claude' | 'gemini';

export interface AiPickOption {
  symbol: string;
  companyName: string | null;
  engine: AiPickEngine;
  entry: number;
}

function dedupeBySymbolKeepingLatest<T extends { symbol: string }>(picks: T[]): T[] {
  const bySymbol = new Map<string, T>();
  for (const p of picks) {
    if (!bySymbol.has(p.symbol)) bySymbol.set(p.symbol, p);
  }
  return [...bySymbol.values()];
}

export function AiPickSelector({ onSelect }: { onSelect: (option: AiPickOption) => void }): ReactNode {
  const [options, setOptions] = useState<AiPickOption[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const date = todayJst();
    Promise.all([
      fetchPicks('mid_term', { date, limit: 50 }),
      fetchPicks('short_term', { date, limit: 50 }),
      fetchGeminiPicks('mid_term', { date, limit: 50 }),
      fetchGeminiPicks('short_term', { date, limit: 50 }),
    ])
      .then(([claudeMid, claudeShort, geminiMid, geminiShort]) => {
        const claude = dedupeBySymbolKeepingLatest<PickSummary>([...claudeMid, ...claudeShort]).map(
          (p): AiPickOption => ({ symbol: p.symbol, companyName: p.company_name, engine: 'claude', entry: p.entry }),
        );
        const gemini = dedupeBySymbolKeepingLatest<GeminiPickSummary>([...geminiMid, ...geminiShort]).map(
          (p): AiPickOption => ({ symbol: p.symbol, companyName: p.company_name, engine: 'gemini', entry: p.entry }),
        );
        setOptions([...claude, ...gemini]);
      })
      .catch(() => setError('本日のAIピック一覧の取得に失敗しました'));
  }, []);

  return (
    <div className="ai-pick-selector">
      <p className="ai-pick-selector-label">本日の AI ピックから追加</p>
      {error && <p className="signal-queue-error">{error}</p>}
      {!error && options.length === 0 && <p className="signal-queue-empty">本日のAIピックはまだありません</p>}
      {options.length > 0 && (
        <ul className="ai-pick-selector-list">
          {options.map((o) => (
            <li key={`${o.engine}-${o.symbol}`}>
              <button type="button" onClick={() => onSelect(o)}>
                <span className="ai-pick-selector-badge">{o.engine === 'claude' ? 'Claude' : 'Gemini'}</span>
                <span>
                  {o.symbol}
                  {o.companyName && `（${o.companyName}）`}
                </span>
                <span className="ai-pick-selector-price">¥{Math.round(o.entry).toLocaleString('ja-JP')}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
