'use client';

import { useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { addHolding } from '@/lib/api/portfolio';
import { todayJst } from '@/lib/jstDate';
import './portfolio.css';

// 銘柄検索・AIピックのどちらから開いても同じ入力（株数・取得単価・取得日）を集める
// ポートフォリオへの追加ポップアップ（🆕 P26、ユーザー指示）。

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
  const [acquiredAt, setAcquiredAt] = useState(todayJst());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
          <input type="number" min={0} step={0.01} value={avgCost} onChange={(e) => setAvgCost(e.target.value)} required />
        </label>
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
