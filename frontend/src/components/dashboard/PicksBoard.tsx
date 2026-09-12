'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchPickDetail, fetchPicks, runPicks, type HorizonType, type PickDetail, type PickSummary } from '@/lib/api/picks';
import { fetchStockNote, type StockNote } from '@/lib/api/stock';
import './dashboard.css';

type SortKey = 'confidence' | 'expected_return' | 'symbol';

const SORT_LABELS: Record<SortKey, string> = {
  confidence: 'AI信頼度',
  expected_return: '期待リターン',
  symbol: '銘柄コード',
};

function expectedReturnPct(p: PickSummary): number {
  return p.entry === 0 ? 0 : ((p.target - p.entry) / p.entry) * 100;
}

function sortPicks(picks: readonly PickSummary[], key: SortKey): PickSummary[] {
  const sorted = [...picks];
  if (key === 'confidence') sorted.sort((a, b) => b.confidence - a.confidence);
  else if (key === 'expected_return') sorted.sort((a, b) => expectedReturnPct(b) - expectedReturnPct(a));
  else sorted.sort((a, b) => a.symbol.localeCompare(b.symbol));
  return sorted;
}

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
      {detail.shadow_predictions.length > 0 && (
        <>
          <h3 className="pick-detail-subheading">他の LLM による判定（参考、比較用）</h3>
          <ul className="pick-detail-shadow-list">
            {detail.shadow_predictions.map((shadow) => (
              <li key={shadow.shadow_id} className="pick-detail-shadow-item">
                <p className="pick-detail-shadow-header">
                  <span>{shadow.challenger_version}</span>
                  <span style={{ color: directionColor(shadow.direction) }}>
                    {DIRECTION_LABELS[shadow.direction]}（確度 {shadow.confidence.toFixed(0)}）
                  </span>
                </p>
                <p className="pick-detail-shadow-bracket">
                  買値 {formatYen(shadow.entry)} / 損切値 {formatYen(shadow.stop)} / 売値 {formatYen(shadow.target)}
                </p>
                {shadow.reasoning && <p>{shadow.reasoning}</p>}
                {shadow.risk_factors.length > 0 && (
                  <ul>
                    {shadow.risk_factors.map((factor, i) => (

                      <li key={i}>{factor}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
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
  const [sortKey, setSortKey] = useState<SortKey>('confidence');

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

  const sortedPicks = useMemo(() => sortPicks(picks, sortKey), [picks, sortKey]);

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
      key: 'current_price',
      header: '現在値 / 前日比',
      numeric: true,
      render: (p) =>
        p.current_price === null ? (
          '—'
        ) : (
          <span className="pick-current-price-cell">
            <span>{formatYen(p.current_price)}</span>
            {p.change_pct !== null && (
              <span style={{ color: directionColor(p.change_pct > 0 ? 'bullish' : p.change_pct < 0 ? 'bearish' : 'neutral') }}>
                {p.change_pct > 0 ? '+' : ''}
                {p.change_pct.toFixed(2)}%
              </span>
            )}
          </span>
        ),
    },
    {
      key: 'direction',
      header: '方向',
      render: (p) => <span style={{ color: directionColor(p.direction) }}>{DIRECTION_LABELS[p.direction]}</span>,
    },
    { key: 'entry', header: '推奨買値', numeric: true, render: (p) => formatYen(p.entry) },
    { key: 'stop', header: '推奨損切値', numeric: true, render: (p) => formatYen(p.stop) },
    {
      key: 'target',
      header: '推奨売値',
      numeric: true,
      render: (p) => (
        <span className="pick-target-cell">
          <span>{formatYen(p.target)}</span>
          <span className="pick-target-return">想定 {expectedReturnPct(p) >= 0 ? '+' : ''}{expectedReturnPct(p).toFixed(1)}%</span>
        </span>
      ),
    },
    {
      key: 'confidence',
      header: 'AI信頼度',
      numeric: true,
      render: (p) => (
        <span className="pick-confidence-cell">
          <span>
            {p.confidence.toFixed(0)}（{BUCKET_LABELS[p.confidence_bucket]}）
          </span>
          <span className="pick-confidence-bar" aria-hidden="true">
            <span className="pick-confidence-bar-fill" style={{ width: `${Math.min(100, Math.max(0, p.confidence))}%` }} />
          </span>
        </span>
      ),
    },
    {
      key: 'rationale_text',
      header: '根拠プレビュー',
      render: (p) => (
        <span className="pick-rationale-cell">
          <span title={p.rationale_text}>{truncate(p.rationale_text)}</span>
          {p.reasoning_tags.length > 0 && (
            <span className="pick-tag-list">
              {p.reasoning_tags.map((tag) => (
                <span key={tag} className="pick-tag-chip">
                  {tag}
                </span>
              ))}
            </span>
          )}
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
        <div className="picks-board-sort" role="group" aria-label="並び替え">
          <span className="picks-board-sort-label">並び替え</span>
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={sortKey === key ? 'is-active' : undefined}
              aria-pressed={sortKey === key}
              onClick={() => setSortKey(key)}
            >
              {SORT_LABELS[key]}
            </button>
          ))}
        </div>
        <button type="button" onClick={handleRun} disabled={running}>
          {running ? '実行中…' : '手動更新'}
        </button>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      <DataTable
        caption="本日の AI 銘柄ピック（並び替え可能）"
        columns={COLUMNS}
        rows={sortedPicks}
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
