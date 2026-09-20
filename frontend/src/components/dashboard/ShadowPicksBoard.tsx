'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
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
import { fetchShadowPicks, type ShadowPickSummary, type HorizonType } from '@/lib/api/picks';
import { challengerProviderLabel, useOfficialProviderLabel } from '@/lib/llmProviderLabels';
import { todayJst } from '@/lib/jstDate';
import './dashboard.css';

// シャドウ（challenger LLM）による判定の一覧。公式パイプライン（PicksBoard）と同じ候補を、
// 独立した「別視点の意見」として比較表示する。複数プロバイダを併用している場合は
// プロバイダごとに別行として表示され、行ごとのバッジで判別できる。
// あくまで比較参考用の表示であり、シャドウ単独では売買提案としての採否判定や台帳化は行わない
// （実行主体は常に公式パイプライン/prediction_ledger、CLAUDE.md）。そのため手動更新ボタンは
// 持たず、ダッシュボードの「手動更新」（公式パイプライン側）に連動して生成される。

export function ShadowPicksBoard(): ReactNode {
  const [horizon, setHorizon] = useState<HorizonType>('mid_term');
  const [picks, setPicks] = useState<ShadowPickSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [noteModalSymbol, setNoteModalSymbol] = useState<string | null>(null);
  const [officialPickId, setOfficialPickId] = useState<string | null>(null);
  const [addHoldingPick, setAddHoldingPick] = useState<ShadowPickSummary | null>(null);
  const officialLabel = useOfficialProviderLabel('stock_pick');

  const load = useCallback((h: HorizonType) => {
    fetchShadowPicks(h, { date: todayJst(), limit: 50 })
      .then(setPicks)
      .catch(() => setError('シャドウ判定一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    load(horizon);
  }, [load, horizon]);

  const sortedPicks = [...picks].sort((a, b) => b.confidence - a.confidence);

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
        シャドウプロバイダが{officialLabel}（公式パイプライン）と同じ候補を独立に判定した結果です。
        あくまで比較参考用で、売買提案の採否・台帳化は行いません。{officialLabel}側の「手動更新」を
        押すと一緒に更新されます。
      </p>

      {error && <p className="signal-queue-error">{error}</p>}

      {sortedPicks.length === 0 ? (
        <p className="data-table-empty">本日のシャドウ判定はまだありません</p>
      ) : (
        <ul className="pick-card-list" aria-label="シャドウ（challenger LLM）による銘柄ピック一覧（比較参考用）">
          {sortedPicks.map((p) => (
            <li key={p.shadow_id} className="pick-card pick-card-shadow">
              <div className="pick-card-header">
                <div className="pick-symbol-cell">
                  <span className="pick-symbol-row">
                    <button type="button" className="pick-symbol-link" onClick={() => setNoteModalSymbol(p.symbol)}>
                      {p.symbol}
                      {p.company_name && `（${p.company_name}）`}
                    </button>
                    <Sparkline values={p.spark} color={sparkColor(p.spark)} />
                  </span>
                  <span className="pick-engine-badge" title={`このピックは ${p.challenger_version} が生成しました`}>
                    {challengerProviderLabel(p.challenger_version)}
                  </span>
                </div>
                <div className="pick-current-price-cell">
                  {p.current_price === null ? (
                    <span>—</span>
                  ) : (
                    <>
                      <span className="pick-card-price">{formatYen(p.current_price)}</span>
                      {p.change_pct !== null && (
                        <span
                          style={{
                            color: directionColor(p.change_pct > 0 ? 'bullish' : p.change_pct < 0 ? 'bearish' : 'neutral'),
                          }}
                        >
                          {p.change_pct > 0 ? '+' : ''}
                          {p.change_pct.toFixed(2)}%
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="pick-card-bracket-row">
                <div className="pick-card-bracket-item">
                  <span className="pick-card-bracket-label">方向</span>
                  <span className="pick-card-direction" style={{ color: directionColor(p.direction) }}>
                    {DIRECTION_LABELS[p.direction]}
                  </span>
                </div>
                <div className="pick-card-bracket-item">
                  <span className="pick-card-bracket-label">推奨買値</span>
                  <span className="pick-card-bracket-value">{formatYen(p.entry)}</span>
                </div>
                <div className="pick-card-bracket-item">
                  <span className="pick-card-bracket-label">推奨損切値</span>
                  <span className="pick-card-bracket-value">{formatYen(p.stop)}</span>
                </div>
                <div className="pick-card-bracket-item">
                  <span className="pick-card-bracket-label">推奨売値</span>
                  <span className="pick-card-bracket-value">{formatYen(p.target)}</span>
                  <span className="pick-target-return">
                    想定 {expectedReturnPct(p.entry, p.target) >= 0 ? '+' : ''}
                    {expectedReturnPct(p.entry, p.target).toFixed(1)}%
                  </span>
                </div>
                <div className="pick-card-bracket-item pick-card-bracket-item-wide">
                  <span className="pick-card-bracket-label">確度 {p.confidence.toFixed(0)}</span>
                  <span className="pick-confidence-bar" aria-hidden="true">
                    <span
                      className="pick-confidence-bar-fill"
                      style={{ width: `${Math.min(100, Math.max(0, p.confidence))}%` }}
                    />
                  </span>
                </div>
              </div>

              {p.reasoning && <p className="pick-card-rationale">{p.reasoning}</p>}

              <div className="pick-card-footer">
                {p.risk_factors.length > 0 && (
                  <span className="pick-tag-list">
                    {p.risk_factors.map((tag) => (
                      <span key={tag} className="pick-tag-chip">
                        {tag}
                      </span>
                    ))}
                  </span>
                )}
                <span className="pick-action-group">
                  {p.pick_id && (
                    <button type="button" onClick={() => setOfficialPickId(p.pick_id)}>
                      {officialLabel}版と比較
                    </button>
                  )}
                  <button type="button" onClick={() => setAddHoldingPick(p)}>
                    ポートフォリオに追加
                  </button>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {noteModalSymbol && (
        <Modal title={`ナレッジベースノート: ${noteModalSymbol}`} onClose={() => setNoteModalSymbol(null)}>
          <NoteModalBody key={noteModalSymbol} symbol={noteModalSymbol} />
        </Modal>
      )}

      {officialPickId && (
        <Modal title={`${officialLabel}版のピック詳細`} onClose={() => setOfficialPickId(null)} variant="panel">
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
