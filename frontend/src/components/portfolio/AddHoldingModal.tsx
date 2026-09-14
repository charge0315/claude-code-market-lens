'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { addHolding } from '@/lib/api/portfolio';
import { fetchQuote } from '@/lib/api/stock';
import { todayJst } from '@/lib/jstDate';
import './portfolio.css';

// 銘柄検索・AIピックのどちらから開いても同じ入力（株数・取得単価・取得日）を集める
// ポートフォリオへの追加ポップアップ（🆕 P26、ユーザー指示）。
//
// 取得単価は「その時点の最新株価」を初期値にする（ユーザー指示）。AIピック由来の
// suggestedPrice はピック生成時点の値で開くまでの間に古くなりうるため、モーダルを開く
// たびに /stock/{symbol}/quote で取り直し、取得できた場合のみ上書きする。取得失敗・
// 未取得銘柄では suggestedPrice（無ければ空欄）にフォールバックし、常に手入力で確定できる。

export function AddHoldingModal({
  symbol,
  companyName,
  suggestedPrice,
  onClose,
  onAdded,
}: {
  symbol: string;
  companyName?: string | null;
  suggestedPrice?: number | null;
  onClose: () => void;
  onAdded: () => void;
}): ReactNode {
  const [quantity, setQuantity] = useState('100');
  const [avgCost, setAvgCost] = useState(suggestedPrice ? String(Math.round(suggestedPrice)) : '');
  const [priceAsOf, setPriceAsOf] = useState<'latest' | 'suggested' | null>(suggestedPrice ? 'suggested' : null);
  const [acquiredAt, setAcquiredAt] = useState(todayJst());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchQuote(symbol)
      .then((quote) => {
        if (cancelled || quote.price === null) return;
        setAvgCost(String(Math.round(quote.price)));
        setPriceAsOf('latest');
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    const quantityNum = Number(quantity);
    const avgCostNum = Number(avgCost);
    if (!Number.isFinite(quantityNum) || quantityNum <= 0) {
      setError('株数は正の整数で入力してください');
      return;
    }
    if (!Number.isFinite(avgCostNum) || avgCostNum <= 0) {
      setError('取得単価は正の値で入力してください');
      return;
    }

    setSaving(true);
    setError(null);
    addHolding({ symbol, quantity: Math.round(quantityNum), avg_cost: avgCostNum, acquired_at: acquiredAt })
      .then(() => {
        onAdded();
        onClose();
      })
      .catch(() => setError('追加に失敗しました（同一銘柄・同一取得日のロットが既にある可能性があります）'))
      .finally(() => setSaving(false));
  };

  return (
    <Modal title={`ポートフォリオに追加: ${symbol}${companyName ? `（${companyName}）` : ''}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="holding-form">
        <label className="holding-form-field">
          株数
          <input type="number" min={1} step={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
        </label>
        <label className="holding-form-field">
          取得単価（円）
          <input
            type="number"
            min={0}
            step={0.01}
            value={avgCost}
            onChange={(e) => {
              setAvgCost(e.target.value);
              setPriceAsOf(null);
            }}
            required
          />
        </label>
        {priceAsOf && (
          <p className="model-lab-as-of">
            {priceAsOf === 'latest' ? '現在値を初期値にしています。' : 'ピック生成時点の目安値です（最新値は取得できませんでした）。'}
            必要に応じて実際の約定単価に書き換えてください。
          </p>
        )}
        <label className="holding-form-field">
          取得日
          <input type="date" value={acquiredAt} onChange={(e) => setAcquiredAt(e.target.value)} required />
        </label>
        {error && <p className="signal-queue-error">{error}</p>}
        <div className="holding-form-actions">
          <button type="button" onClick={onClose} disabled={saving}>
            キャンセル
          </button>
          <button type="submit" disabled={saving}>
            {saving ? '追加中…' : '追加する'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
