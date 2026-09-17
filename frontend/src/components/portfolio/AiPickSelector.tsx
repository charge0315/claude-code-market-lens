'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchPicks, fetchShadowPicks, type PickSummary, type ShadowPickSummary } from '@/lib/api/picks';
import { challengerProviderLabel, useOfficialProviderLabel } from '@/lib/llmProviderLabels';
import { todayJst } from '@/lib/jstDate';
import './portfolio.css';

// 銘柄検索と並ぶもう一つの追加経路: 本日の AI ピック（公式/シャドウ両方）から選んで
// そのまま買い注文（保有追加）ポップアップを開けるようにする（ユーザー指示）。

export type AiPickEngine = 'official' | 'shadow';

export interface AiPickOption {
  symbol: string;
  companyName: string | null;
  engine: AiPickEngine;
  entry: number;
  // engine === 'shadow' の場合のみ設定（バッジのモデル名表示用、"<provider>:<model>" 形式）。
  challengerVersion?: string;
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
  const officialLabel = useOfficialProviderLabel('stock_pick');

  useEffect(() => {
    const date = todayJst();
    Promise.all([
      fetchPicks('mid_term', { date, limit: 50 }),
      fetchPicks('short_term', { date, limit: 50 }),
      fetchShadowPicks('mid_term', { date, limit: 50 }),
      fetchShadowPicks('short_term', { date, limit: 50 }),
    ])
      .then(([officialMid, officialShort, shadowMid, shadowShort]) => {
        const official = dedupeBySymbolKeepingLatest<PickSummary>([...officialMid, ...officialShort]).map(
          (p): AiPickOption => ({ symbol: p.symbol, companyName: p.company_name, engine: 'official', entry: p.entry }),
        );
        const shadow = dedupeBySymbolKeepingLatest<ShadowPickSummary>([...shadowMid, ...shadowShort]).map(
          (p): AiPickOption => ({
            symbol: p.symbol,
            companyName: p.company_name,
            engine: 'shadow',
            entry: p.entry,
            challengerVersion: p.challenger_version,
          }),
        );
        setOptions([...official, ...shadow]);
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
                <span className="ai-pick-selector-badge">
                  {o.engine === 'official' ? officialLabel : challengerProviderLabel(o.challengerVersion ?? '')}
                </span>
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
