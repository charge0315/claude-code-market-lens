'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchPickDetail, fetchPicks, runPicks, type HorizonType, type PickDetail, type PickSummary } from '@/lib/api/picks';
import { fetchStockNote, type StockNote } from '@/lib/api/stock';
import './dashboard.css';

// 本日の AI 銘柄ピック（中長期 / 短期タブ）。確度順（backend が既にソート済み）で表示し、
// 3 値（買値 / 損切値 / 売値）と根拠プレビューを必ず併記する（CLAUDE.md）。
// 銘柄名クリックでナレッジベースノート（本文込み・UI表示専用）、
// 根拠「詳細」ボタンでピック詳細（4分析内訳・寄与度・LLMリスク要因）をポップアップ表示する。

const DIRECTION_LABELS: Record<PickSummary['direction'], string> = {
  bullish: '強気',
  bearish: '弱気',
  neutral: '中立',
};

const BUCKET_LABELS: Record<PickSummary['confidence_bucket'], string> = {
  high: '高',
  mid: '中',
  low: '低',
};

function directionColor(direction: PickSummary['direction']): string {
  if (direction === 'bullish') return 'var(--color-gain)';
  if (direction === 'bearish') return 'var(--color-loss)';
  return 'var(--color-flat)';
}

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function truncate(text: string, max = 50): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function NoteModalBody({ symbol }: { symbol: string }): ReactNode {
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

function DetailModalBody({ pickId }: { pickId: string }): ReactNode {
  const [detail, setDetail] = useState<PickDetail | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPickDetail(pickId)
      .then(setDetail)
      .catch(() => setError('ピック詳細の取得に失敗しました'));
  }, [pickId]);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (detail === undefined) return <p>読み込み中…</p>;
  if (detail === null) return <p className="signal-queue-empty">詳細が見つかりません</p>;

  const riskFactors = detail.rationale_struct.llm_risk_factors;
  const holdingDays = detail.rationale_struct.holding_period_days;

  return (
    <div className="pick-detail-body">
      <p>{detail.rationale_text}</p>
      <h3 className="pick-detail-subheading">4分析内訳</h3>
      <ul className="pick-detail-subscores">
        <li>テクニカル: {detail.sub_scores.technical.toFixed(0)}</li>
        <li>トレンド: {detail.sub_scores.trend.toFixed(0)}</li>
        <li>ファンダメンタル: {detail.sub_scores.fundamental.toFixed(0)}</li>
        <li>センチメント: {detail.sub_scores.sentiment.toFixed(0)}</li>
      </ul>
      <h3 className="pick-detail-subheading">情報源ごとの寄与度</h3>
      <pre className="pick-detail-json">{JSON.stringify(detail.source_contributions, null, 2)}</pre>
      {Array.isArray(riskFactors) && riskFactors.length > 0 && (
        <>
          <h3 className="pick-detail-subheading">AI が挙げたリスク要因</h3>
          <ul>
            {riskFactors.map((factor, i) => (
               
              <li key={i}>{String(factor)}</li>
            ))}
          </ul>
        </>
      )}
      {typeof holdingDays === 'number' && <p className="model-lab-brier">想定保有期間: 約{holdingDays}営業日</p>}
    </div>
  );
}

export function PicksBoard(): ReactNode {
  const [horizon, setHorizon] = useState<HorizonType>('mid_term');
  const [picks, setPicks] = useState<PickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [noteModalSymbol, setNoteModalSymbol] = useState<string | null>(null);
  const [detailModalPickId, setDetailModalPickId] = useState<string | null>(null);

  const load = useCallback((h: HorizonType) => {
    fetchPicks(h, { limit: 50 })
      .then(setPicks)
      .catch(() => setError('ピック一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    load(horizon);
  }, [load, horizon]);

  const handleRun = (): void => {
    setRunning(true);
    setError(null);
    runPicks(horizon)
      .then((result) => {
        if (result.status !== 'ok' && result.message) {
          setError(result.message);
        }
        load(horizon);
      })
      .catch(() => setError('ピック生成に失敗しました'))
      .finally(() => setRunning(false));
  };

  const COLUMNS: ReadonlyArray<Column<PickSummary>> = [
    {
      key: 'symbol',
      header: '銘柄',
      render: (p) => (
        <button type="button" className="pick-symbol-link" onClick={() => setNoteModalSymbol(p.symbol)}>
          {p.symbol}
          {p.company_name && `（${p.company_name}）`}
        </button>
      ),
    },
    {
      key: 'direction',
      header: '方向',
      render: (p) => <span style={{ color: directionColor(p.direction) }}>{DIRECTION_LABELS[p.direction]}</span>,
    },
    {
      key: 'confidence',
      header: '確度',
      numeric: true,
      render: (p) => `${p.confidence.toFixed(0)}（${BUCKET_LABELS[p.confidence_bucket]}）`,
    },
    { key: 'entry', header: '買値目安', numeric: true, render: (p) => formatYen(p.entry) },
    { key: 'stop', header: '損切値', numeric: true, render: (p) => formatYen(p.stop) },
    { key: 'target', header: '推奨売値', numeric: true, render: (p) => formatYen(p.target) },
    {
      key: 'rationale_text',
      header: '根拠プレビュー',
      render: (p) => (
        <span className="pick-rationale-cell">
          <span title={p.rationale_text}>{truncate(p.rationale_text)}</span>
          <button type="button" onClick={() => setDetailModalPickId(p.pick_id)}>
            詳細
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="picks-board">
      <div className="picks-board-toolbar">
        <div className="picks-board-tabs" role="group" aria-label="ホライズン">
          <button
            type="button"
            className={horizon === 'mid_term' ? 'is-active' : undefined}
            aria-pressed={horizon === 'mid_term'}
            onClick={() => setHorizon('mid_term')}
          >
            中長期
          </button>
          <button
            type="button"
            className={horizon === 'short_term' ? 'is-active' : undefined}
            aria-pressed={horizon === 'short_term'}
            onClick={() => setHorizon('short_term')}
          >
            短期
          </button>
        </div>
        <button type="button" onClick={handleRun} disabled={running}>
          {running ? '実行中…' : '手動更新'}
        </button>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      <DataTable
        caption="本日の AI 銘柄ピック（確度順）"
        columns={COLUMNS}
        rows={picks}
        rowKey={(p) => p.pick_id}
        emptyMessage="本日のピックはまだありません"
      />

      {noteModalSymbol && (
        <Modal title={`ナレッジベースノート: ${noteModalSymbol}`} onClose={() => setNoteModalSymbol(null)}>
          <NoteModalBody key={noteModalSymbol} symbol={noteModalSymbol} />
        </Modal>
      )}

      {detailModalPickId && (
        <Modal title="ピック詳細・根拠" onClose={() => setDetailModalPickId(null)}>
          <DetailModalBody key={detailModalPickId} pickId={detailModalPickId} />
        </Modal>
      )}
    </div>
  );
}
