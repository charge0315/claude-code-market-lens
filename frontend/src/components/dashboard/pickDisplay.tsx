'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchStockNote, type StockNote } from '@/lib/api/stock';
import type { Direction } from '@/lib/api/picks';

// Claude（公式）ピック・Gemini（比較）ピックの両テーブルで共用する表示ヘルパー（🆕 P25）。

export const DIRECTION_LABELS: Record<Direction, string> = {
  bullish: '強気',
  bearish: '弱気',
  neutral: '中立',
};

export function directionColor(direction: Direction): string {
  if (direction === 'bullish') return 'var(--color-gain)';
  if (direction === 'bearish') return 'var(--color-loss)';
  return 'var(--color-flat)';
}

// スパークラインの色は「そのピックの強気/弱気判定」ではなく、系列そのものの
// 始点→終点の値動きに従って色分けする（見たままの値動きを示すため）。
export function sparkColor(spark: readonly number[]): string {
  if (spark.length < 2) return 'var(--color-flat)';
  const delta = spark[spark.length - 1] - spark[0];
  if (delta > 0) return 'var(--color-gain)';
  if (delta < 0) return 'var(--color-loss)';
  return 'var(--color-flat)';
}

export function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

export function expectedReturnPct(entry: number, target: number): number {
  return entry === 0 ? 0 : ((target - entry) / entry) * 100;
}

export function truncate(text: string, max = 50): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function NoteModalBody({ symbol }: { symbol: string }): ReactNode {
  const [note, setNote] = useState<StockNote | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStockNote(symbol)
      .then(setNote)
      .catch(() => setError('ナレッジベースノートの取得に失敗しました'));
  }, [symbol]);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (note === undefined) return <p>読み込み中…</p>;
  if (note === null) return <p className="signal-queue-empty">この銘柄のナレッジベースノートはまだありません</p>;
  return <>{note.content}</>;
}
