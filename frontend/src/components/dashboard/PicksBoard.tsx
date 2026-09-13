'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Sparkline } from '@/components/ui/Sparkline';
import { PickDetailPanel } from '@/components/dashboard/PickDetailPanel';
import {
  DIRECTION_LABELS,
  NoteModalBody,
  directionColor,
  expectedReturnPct as expectedReturnPctOf,
  formatYen,
  sparkColor,
  truncate,
} from '@/components/dashboard/pickDisplay';
import { AddHoldingModal } from '@/components/portfolio/AddHoldingModal';
import { fetchPicks, runPicks, type HorizonType, type PickSummary } from '@/lib/api/picks';
import { todayJst } from '@/lib/jstDate';
import './dashboard.css';

type SortKey = 'confidence' | 'expected_return' | 'symbol';

const SORT_LABELS: Record<SortKey, string> = {
  confidence: 'AI信頼度',
  expected_return: '期待リターン',
  symbol: '銘柄コード',
};

function expectedReturnPct(p: PickSummary): number {
  return expectedReturnPctOf(p.entry, p.target);
}

function sortPicks(picks: readonly PickSummary[], key: SortKey): PickSummary[] {
  const sorted = [...picks];
  if (key === 'confidence') sorted.sort((a, b) => b.confidence - a.confidence);
  else if (key === 'expected_return') sorted.sort((a, b) => expectedReturnPct(b) - expectedReturnPct(a));
  else sorted.sort((a, b) => a.symbol.localeCompare(b.symbol));
  return sorted;
}

// Claude（公式パイプライン）による、本日の AI 銘柄ピック（中長期 / 短期タブ）。
// 確度順（backend が既にソート済み）で表示し、3 値（買値 / 損切値 / 売値）と根拠プレビューを
// 必ず併記する（CLAUDE.md）。銘柄名クリックでナレッジベースノート（本文込み・UI表示専用）、
// 根拠「詳細」ボタンでピック詳細（4分析内訳・寄与度・LLMリスク要因）をポップアップ表示する。
// Gemini（challenger LLM）の判定は混在させず、別コンポーネント（GeminiPicksBoard）で表示する
// （🆕 P25、ユーザー指示: エンジンごとに分けて表示）。

const BUCKET_LABELS: Record<PickSummary['confidence_bucket'], string> = {
  high: '高',
  mid: '中',
  low: '低',
};

export function PicksBoard(): ReactNode {
  const [horizon, setHorizon] = useState<HorizonType>('mid_term');
  const [picks, setPicks] = useState<PickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [noteModalSymbol, setNoteModalSymbol] = useState<string | null>(null);
  const [detailModalPickId, setDetailModalPickId] = useState<string | null>(null);
  const [addHoldingPick, setAddHoldingPick] = useState<PickSummary | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('confidence');

  const load = useCallback((h: HorizonType) => {
    // 見出し・空表示ともに「本日の」ピックと明記しているため、日付を指定せず全期間の
    // 最新50件を取得すると前日以前の分まで混ざって同一銘柄が重複して見える
    // （台帳は日ごとに新しい行を追記する設計のため）。JST の当日分だけに絞り込む。
    fetchPicks(h, { date: todayJst(), limit: 50 })
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
        <span className="pick-symbol-cell">
          <span className="pick-symbol-row">
            <button type="button" className="pick-symbol-link" onClick={() => setNoteModalSymbol(p.symbol)}>
              {p.symbol}
              {p.company_name && `（${p.company_name}）`}
            </button>
            <Sparkline values={p.spark} color={sparkColor(p.spark)} />
          </span>
          {/* 公式パイプラインは常に Anthropic（Claude）が生成する（未設定なら run_picks
              自体が status='not_configured' で早期リターンし台帳化されない）。Gemini は
              shadow_predictions への比較用判定のみで、ここには載らない。 */}
          <span className="pick-engine-badge" title="このピックは Claude（Anthropic）が生成しました">
            Claude
          </span>
        </span>
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
          <span className="pick-action-group">
            <button type="button" onClick={() => setDetailModalPickId(p.pick_id)}>
              詳細
            </button>
            <button type="button" onClick={() => setAddHoldingPick(p)}>
              ポートフォリオに追加
            </button>
          </span>
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

      {detailModalPickId &&
        (() => {
          const target = picks.find((p) => p.pick_id === detailModalPickId);
          const title = target ? `${target.symbol}${target.company_name ? `（${target.company_name}）` : ''}` : 'ピック詳細';
          return (
            <Modal title={title} onClose={() => setDetailModalPickId(null)} variant="panel">
              <PickDetailPanel key={detailModalPickId} pickId={detailModalPickId} />
            </Modal>
          );
        })()}

      {addHoldingPick && (
        <AddHoldingModal
          symbol={addHoldingPick.symbol}
          companyName={addHoldingPick.company_name}
          suggestedPrice={addHoldingPick.entry}
          onClose={() => setAddHoldingPick(null)}
          onAdded={() => undefined}
        />
      )}
    </div>
  );
}
