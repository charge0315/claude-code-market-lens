'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { StageDag } from '@/components/pipeline/StageDag';
import { ThinkingPanel } from '@/components/pipeline/ThinkingPanel';
import { DIRECTION_LABELS, directionColor, formatYen } from '@/components/dashboard/pickDisplay';
import { ApiError } from '@/lib/api/client';
import { fetchSandboxShadow, triggerSandboxInference } from '@/lib/api/inference';
import { challengerDetailLabel } from '@/lib/llmProviderLabels';
import type { HorizonType, ShadowPrediction } from '@/lib/api/picks';
import { deriveSnapshot } from '@/lib/pipeline/deriveSnapshot';
import { usePipelineTrace } from '@/lib/pipeline/usePipelineTrace';
import './chart.css';

// chart画面「AI推論トレース」タブ（🆕 P36）— 任意銘柄（本日の AI ピック対象外も含む）で
// その場から推論を1回だけ実行し、4分析〜検証ゲートまでの経緯をライブ表示する。
// `POST /api/inference/sandbox` は `prediction_ledger` を一切汚さない「試し打ち」実行のため、
// ライブ表示は既存 `usePipelineTrace`/`StageDag`/`ThinkingPanel`（銘柄詳細画面のトレース
// ビューアと共通）をそのまま再利用する。

const HORIZON_LABELS: Record<HorizonType, string> = { mid_term: '中長期', short_term: '短期' };
const HORIZON_TYPES: HorizonType[] = ['mid_term', 'short_term'];

function triggerErrorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 429) return '本日のLLM利用コスト上限に達したため実行できません';
  if (e instanceof ApiError && e.status === 409) return 'この銘柄は既に推論を実行中です';
  return '推論の開始に失敗しました';
}

export function SandboxInferencePanel({ symbol }: { symbol: string }): ReactNode {
  const [horizonType, setHorizonType] = useState<HorizonType>('mid_term');
  const [runId, setRunId] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [shadows, setShadows] = useState<ShadowPrediction[] | null>(null);
  const [shadowError, setShadowError] = useState<string | null>(null);

  // symbol が切り替わったら前の銘柄の実行結果を引きずらない。effect内の無条件 setState は
  // 避け、レンダー中に前回値と比較して直ちに setState する React 公式パターンを使う
  // （`lib/pipeline/usePipelineTrace.ts` と同じ慣習）。
  const [prevSymbol, setPrevSymbol] = useState(symbol);
  if (symbol !== prevSymbol) {
    setPrevSymbol(symbol);
    setRunId(null);
    setTriggerError(null);
    setShadows(null);
    setShadowError(null);
  }

  const { events, error: streamError, isActive } = usePipelineTrace(runId, 'live');
  const snapshot = runId ? deriveSnapshot(runId, events) : null;

  useEffect(() => {
    if (!runId || isActive || snapshot?.status !== 'done') return;
    fetchSandboxShadow(runId)
      .then(setShadows)
      .catch(() => setShadowError('他 LLM 判定の取得に失敗しました'));
  }, [runId, isActive, snapshot?.status]);

  async function handleTrigger(): Promise<void> {
    setTriggering(true);
    setTriggerError(null);
    setShadows(null);
    setShadowError(null);
    try {
      const res = await triggerSandboxInference(symbol, horizonType);
      setRunId(res.run_id);
    } catch (e) {
      setTriggerError(triggerErrorMessage(e));
    } finally {
      setTriggering(false);
    }
  }

  const running = triggering || isActive;

  return (
    <div className="sandbox-inference-panel">
      <p className="sandbox-inference-note">
        任意銘柄（本日の AI ピック対象外も含む）でAI推論をその場から実行し、4分析から検証ゲートまでの経緯をライブ表示します。
        実行ごとにLLM呼び出しが発生し課金対象です。この実行結果は予測台帳には記録されません。
      </p>

      <div className="sandbox-inference-toolbar">
        <div className="chart-view-toolbar" role="group" aria-label="ホライズン">
          {HORIZON_TYPES.map((h) => (
            <button
              key={h}
              type="button"
              className={horizonType === h ? 'is-active' : undefined}
              aria-pressed={horizonType === h}
              disabled={running}
              onClick={() => setHorizonType(h)}
            >
              {HORIZON_LABELS[h]}
            </button>
          ))}
        </div>
        <button type="button" className="sandbox-inference-trigger" onClick={() => void handleTrigger()} disabled={running}>
          {running ? '実行中…' : 'AI推論を実行'}
        </button>
      </div>

      {triggerError && <p className="signal-queue-error">{triggerError}</p>}
      {streamError && <p className="signal-queue-error">{streamError}</p>}

      {snapshot ? (
        <>
          <StageDag snapshot={snapshot} />
          <ThinkingPanel events={events} />
        </>
      ) : (
        !triggering && (
          <p className="signal-queue-empty">「AI推論を実行」を押すと、4分析から検証ゲートまでの経緯がここに表示されます</p>
        )
      )}

      {shadowError && <p className="signal-queue-error">{shadowError}</p>}
      {shadows && shadows.length > 0 && (
        <>
          <h3 className="sandbox-inference-subheading">他 LLM による判定（参考、比較用）</h3>
          <ul className="sandbox-inference-shadow-list">
            {shadows.map((shadow) => (
              <li key={shadow.shadow_id} className="sandbox-inference-shadow-item">
                <p className="sandbox-inference-shadow-header">
                  <span>{challengerDetailLabel(shadow.challenger_version)}</span>
                  <span style={{ color: directionColor(shadow.direction) }}>
                    {DIRECTION_LABELS[shadow.direction]}（確度 {shadow.confidence.toFixed(0)}）
                  </span>
                </p>
                <p className="sandbox-inference-shadow-bracket">
                  買値 {formatYen(shadow.entry)} / 損切値 {formatYen(shadow.stop)} / 売値 {formatYen(shadow.target)}
                </p>
                {shadow.reasoning && <p>{shadow.reasoning}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
