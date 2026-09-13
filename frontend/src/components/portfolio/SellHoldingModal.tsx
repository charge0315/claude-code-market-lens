'use client';

import { useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { sellHolding } from '@/lib/api/portfolio';
import { todayJst } from '@/lib/jstDate';
import type { PortfolioHolding } from '@/lib/api/portfolio';
import './portfolio.css';

// 保有銘柄の売却ポップアップ（🆕 P26）。売却株数が保有株数と同じなら全量売却（ロット削除）、
// それ未満なら一部売却として backend 側で扱う（`services/db/portfolio_db` 参照）。

export function SellHoldingModal({
  holding,
  onClose,
  onSold,
}: {
  holding: PortfolioHolding;
  onClose: () => void;
  onSold: () => void;
}): ReactNode {
  const [quantity, setQuantity] = useState(String(holding.quantity));
  const [sellPrice, setSellPrice] = useState(holding.current_price ? String(Math.round(holding.current_price)) : '');
  const [soldAt, setSoldAt] = useState(todayJst());
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    const quantityNum = Number(quantity);
    const sellPriceNum = Number(sellPrice);
    if (!Number.isFinite(quantityNum) || quantityNum <= 0 || quantityNum > holding.quantity) {
      setError(`売却株数は1〜${holding.quantity}の範囲で入力してください`);
      return;
    }
    if (!Number.isFinite(sellPriceNum) || sellPriceNum <= 0) {
      setError('売却価格は正の値で入力してください');
      return;
    }

    setSaving(true);
    setError(null);
    sellHolding(holding.holding_id, {
      quantity: Math.round(quantityNum),
      sell_price: sellPriceNum,
      sold_at: soldAt,
      note: note.trim() || null,
    })
      .then(() => {
        onSold();
        onClose();
      })
      .catch(() => setError('売却の記録に失敗しました'))
      .finally(() => setSaving(false));
  };

  return (
    <Modal title={`売却: ${holding.symbol}${holding.company_name ? `（${holding.company_name}）` : ''}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="holding-form">
        <p className="model-lab-as-of">
          保有株数 {holding.quantity} 株 / 取得単価 ¥{Math.round(holding.avg_cost).toLocaleString('ja-JP')}
        </p>
        <label className="holding-form-field">
          売却株数
          <input
            type="number"
            min={1}
            max={holding.quantity}
            step={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </label>
        <label className="holding-form-field">
          売却価格（円）
          <input type="number" min={0} step={0.01} value={sellPrice} onChange={(e) => setSellPrice(e.target.value)} required />
        </label>
        <label className="holding-form-field">
          売却日
          <input type="date" value={soldAt} onChange={(e) => setSoldAt(e.target.value)} required />
        </label>
        <label className="holding-form-field">
          メモ（任意）
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <p className="signal-queue-error">{error}</p>}
        <div className="holding-form-actions">
          <button type="button" onClick={onClose} disabled={saving}>
            キャンセル
          </button>
          <button type="submit" disabled={saving}>
            {saving ? '記録中…' : '売却する'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
