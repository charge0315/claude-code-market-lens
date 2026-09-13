'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { searchStocks, type TickerInfo } from '@/lib/api/stock';
import './stocksearchbox.css';

const DEBOUNCE_MS = 300;

// 証券コード/銘柄名で検索する共用コンポーネント（🆕 P26、当初はポートフォリオ専用だったが
// 銘柄詳細画面でも使うため `ui/` へ移動）。選択後の挙動は呼び出し元が `onSelect` で決める
// （ポートフォリオへの追加ポップアップを開く／銘柄詳細ページへ遷移する、等）。

export function StockSearchBox({ onSelect }: { onSelect: (ticker: TickerInfo) => void }): ReactNode {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TickerInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const trimmed = query.trim();
    timer.current = setTimeout(() => {
      if (!trimmed) {
        setResults([]);
        setOpen(false);
        return;
      }
      searchStocks(trimmed)
        .then((r) => {
          setResults(r);
          setOpen(true);
          setError(null);
        })
        .catch(() => setError('銘柄検索に失敗しました'));
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [query]);

  const handleSelect = (ticker: TickerInfo): void => {
    onSelect(ticker);
    setQuery('');
    setResults([]);
    setOpen(false);
  };

  return (
    <div className="stock-search-box">
      <input
        type="text"
        value={query}
        placeholder="証券コード または 銘柄名で検索（例: 7203 / トヨタ）"
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        aria-label="銘柄検索"
      />
      {error && <p className="stock-search-error">{error}</p>}
      {open && results.length > 0 && (
        <ul className="stock-search-results">
          {results.map((t) => (
            <li key={t.code}>
              <button type="button" onClick={() => handleSelect(t)}>
                {t.code}（{t.name}）
                {t.sector && <span className="stock-search-sector">{t.sector}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && results.length === 0 && query.trim() && <p className="stock-search-empty">該当する銘柄がありません</p>}
    </div>
  );
}
