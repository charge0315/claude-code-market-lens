'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Sparkline } from '@/components/ui/Sparkline';
import { PickDetailPanel } from '@/components/dashboard/PickDetailPanel';
import {
  DIRECTION_LABELS,
  NoteModalBody,
  directionColor,
  expectedReturnPct,
  formatYen,
  sparkColor,
} from '@/components/dashboard/pickDisplay';
import { AddHoldingModal } from '@/components/portfolio/AddHoldingModal';
import { fetchGeminiPicks, type GeminiPickSummary, type HorizonType } from '@/lib/api/picks';
import { todayJst } from '@/lib/jstDate';
import './dashboard.css';

// Gemini（challenger LLM）による判定の一覧（🆕 P25）。Claude（公式パイプライン、
// PicksBoard）と同じ候補を、Claudeとは独立した「別視点の意見」として比較表示する。
// あくまで比較参考用の表示であり、Gemini 単独では売買提案としての採否判定や台帳化は行わない
// （実行主体は常に Claude/prediction_ledger、CLAUDE.md）。そのため手動更新ボタンは持たず、
// ダッシュボードの「手動更新」（Claude側）に連動して生成される。

export function GeminiPicksBoard(): ReactNode {
  const [horizon, setHorizon] = useState<HorizonType>('mid_term');
  const [picks, setPicks] = useState<GeminiPickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [noteModalSymbol, setNoteModalSymbol] = useState<string | null>(null);
  const [officialPickId, setOfficialPickId] = useState<string | null>(null);
  const [addHoldingPick, setAddHoldingPick] = useState<GeminiPickSummary | null>(null);

  const load = useCallback((h: HorizonType) => {
    fetchGeminiPicks(h, { date: todayJst(), limit: 50 })
      .then(setPicks)
      .catch(() => setError('Geminiピック一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    load(horizon);
  }, [load, horizon]);

  const sortedPicks = [...picks].sort((a, b) => b.confidence - a.confidence);

  const COLUMNS: ReadonlyArray<Column<GeminiPickSummary>> = [
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
          <span className="pick-engine-badge" title={`このピックは ${p.challenger_version} が生成しました`}>
            Gemini
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
          <span className="pick-target-return">
            想定 {expectedReturnPct(p.entry, p.target) >= 0 ? '+' : ''}
            {expectedReturnPct(p.entry, p.target).toFixed(1)}%
          </span>
        </span>
      ),
    },
    {
      key: 'confidence',
      header: '確度',
      numeric: true,
      render: (p) => (
        <span className="pick-confidence-cell">
          <span>{p.confidence.toFixed(0)}</span>
          <span className="pick-confidence-bar" aria-hidden="true">
            <span className="pick-confidence-bar-fill" style={{ width: `${Math.min(100, Math.max(0, p.confidence))}%` }} />
          </span>
        </span>
      ),
    },
    {
      key: 'reasoning',
      header: '根拠プレビュー',
      render: (p) => (
        <span className="pick-rationale-cell">
          {p.reasoning && <span title={p.reasoning}>{p.reasoning.length > 50 ? `${p.reasoning.slice(0, 50)}…` : p.reasoning}</span>}
          {p.risk_factors.length > 0 && (
            <span className="pick-tag-list">
              {p.risk_factors.map((tag) => (
                <span key={tag} className="pick-tag-chip">
                  {tag}
                </span>
              ))}
            </span>
          )}
          {p.pick_id && (
            <button type="button" onClick={() => setOfficialPickId(p.pick_id)}>
              Claude版と比較
            </button>
          )}
          <button type="button" onClick={() => setAddHoldingPick(p)}>
            ポートフォリオに追加
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
      </div>

      <p className="model-lab-as-of">
        Gemini が Claude（公式パイプライン）と同じ候補を独立に判定した結果です。あくまで比較参考用で、
        売買提案の採否・台帳化は行いません。Claude側の「手動更新」を押すと一緒に更新されます。
      </p>

      {error && <p className="signal-queue-error">{error}</p>}

      <DataTable
        caption="Gemini（challenger LLM）による銘柄ピック一覧（比較参考用）"
        columns={COLUMNS}
        rows={sortedPicks}
        rowKey={(p) => p.shadow_id}
        emptyMessage="本日のGemini判定はまだありません"
      />

      {noteModalSymbol && (
        <Modal title={`ナレッジベースノート: ${noteModalSymbol}`} onClose={() => setNoteModalSymbol(null)}>
          <NoteModalBody key={noteModalSymbol} symbol={noteModalSymbol} />
        </Modal>
      )}

      {officialPickId && (
        <Modal title="Claude版のピック詳細" onClose={() => setOfficialPickId(null)} variant="panel">
          <PickDetailPanel key={officialPickId} pickId={officialPickId} />
        </Modal>
      )}

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
