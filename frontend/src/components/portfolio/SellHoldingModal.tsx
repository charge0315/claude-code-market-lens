'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { sellHolding } from '@/lib/api/portfolio';
import { fetchQuote } from '@/lib/api/stock';
import { todayJst } from '@/lib/jstDate';
import type { PortfolioHolding } from '@/lib/api/portfolio';
import './portfolio.css';

// 保有銘柄の売却ポップアップ（🆕 P26）。売却株数が保有株数と同じなら全量売却（ロット削除）、
// それ未満なら一部売却として backend 側で扱う（`services/db/portfolio_db` 参照）。
//
// 売却価格は「その時点の最新株価」を初期値にする（ユーザー指示）。holding.current_price は
// ポートフォリオ画面を開いた（＝一覧取得した）時点のスナップショットで、モーダルを開くまでの
// 間に古くなりうるため、開くたびに /stock/{symbol}/quote で取り直す。取得失敗時のみ
// holding.current_price にフォールバックする。

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
  const [priceIsLatest, setPriceIsLatest] = useState(false);
  const [soldAt, setSoldAt] = useState(todayJst());
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchQuote(holding.symbol)
      .then((quote) => {
        if (cancelled || quote.price === null) return;
        setSellPrice(String(Math.round(quote.price)));
        setPriceIsLatest(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [holding.symbol]);

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
          <input
            type="number"
            min={0}
            step={0.01}
            value={sellPrice}
            onChange={(e) => {
              setSellPrice(e.target.value);
              setPriceIsLatest(false);
            }}
            required
          />
        </label>
        {priceIsLatest && (
          <p className="model-lab-as-of">現在値を初期値にしています。実際の約定単価に応じて書き換えてください。</p>
        )}
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
