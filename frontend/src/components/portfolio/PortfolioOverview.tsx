'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { deleteHolding, fetchPortfolio, type PortfolioHolding, type PortfolioSummary } from '@/lib/api/portfolio';
import { StockSearchBox } from '@/components/ui/StockSearchBox';
import { AddHoldingModal } from './AddHoldingModal';
import { AiPickSelector, type AiPickOption } from './AiPickSelector';
import { HoldingsTable } from './HoldingsTable';
import { SellHistoryTable } from './SellHistoryTable';
import { SellHoldingModal } from './SellHoldingModal';
import './portfolio.css';

// 🆕 P26: 保有一覧に、銘柄検索からの追加・売却・削除・売却履歴を追加した。
// 🆕 ポートフォリオ画面自体からも本日の AI ピック（Claude/Gemini）を選んで追加できるようにした
// （ダッシュボードの PicksBoard/GeminiPicksBoard の「ポートフォリオに追加」とは別経路、ユーザー指示）。

interface AddTarget {
  symbol: string;
  companyName: string | null;
  suggestedPrice?: number | null;
}

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function directionColor(value: number): string {
  if (value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

export function PortfolioOverview(): ReactNode {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addTarget, setAddTarget] = useState<AddTarget | null>(null);
  const [sellTarget, setSellTarget] = useState<PortfolioHolding | null>(null);
  const [historyReloadKey, setHistoryReloadKey] = useState(0);

  const load = useCallback(() => {
    fetchPortfolio()
      .then(setSummary)
      .catch(() => setError('ポートフォリオの取得に失敗しました'));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = (holding: PortfolioHolding): void => {
    const label = `${holding.symbol}${holding.company_name ? `（${holding.company_name}）` : ''}`;
    if (!window.confirm(`${label} を削除しますか？（売却履歴には残りません。取り消せません）`)) return;
    deleteHolding(holding.holding_id)
      .then(load)
      .catch(() => setError('削除に失敗しました'));
  };

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (summary === null) return null;

  return (
    <div>
      <StockSearchBox onSelect={(ticker) => setAddTarget({ symbol: ticker.code, companyName: ticker.name })} />
      <AiPickSelector
        onSelect={(option: AiPickOption) =>
          setAddTarget({ symbol: option.symbol, companyName: option.companyName, suggestedPrice: option.entry })
        }
      />

      <dl className="signal-card-bracket" style={{ margin: 'var(--spacing-lg) 0' }}>
        <div>
          <dt>評価額合計</dt>
          <dd>{formatYen(summary.total_value)}</dd>
        </div>
        <div>
          <dt>評価損益</dt>
          <dd style={{ color: directionColor(summary.total_gain_loss) }}>{formatYen(summary.total_gain_loss)}</dd>
        </div>
        <div>
          <dt>騰落率</dt>
          <dd style={{ color: directionColor(summary.total_return_pct) }}>
            {(summary.total_return_pct * 100).toFixed(2)}%
          </dd>
        </div>
      </dl>

      <HoldingsTable holdings={summary.holdings} onSell={setSellTarget} onDelete={handleDelete} />

      <h3 className="model-lab-subheading">売却履歴</h3>
      <SellHistoryTable reloadKey={historyReloadKey} />

      {addTarget && (
        <AddHoldingModal
          symbol={addTarget.symbol}
          companyName={addTarget.companyName}
          suggestedPrice={addTarget.suggestedPrice}
          onClose={() => setAddTarget(null)}
          onAdded={load}
        />
      )}

      {sellTarget && (
        <SellHoldingModal
          holding={sellTarget}
          onClose={() => setSellTarget(null)}
          onSold={() => {
            load();
            setHistoryReloadKey((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
