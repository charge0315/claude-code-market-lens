import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { StageDag } from '@/components/pipeline/StageDag';
import { ThinkingPanel } from '@/components/pipeline/ThinkingPanel';
import { ShapBar } from '@/components/pipeline/ShapBar';
import '@/components/pipeline/pipeline.css';
import type { DagSnapshot, TraceEvent } from '@/lib/pipeline/types';

// P6c 時点のプレビュー用サンプルデータ（バックエンド payload 形状に準拠）。
// P6d でライブ SSE / リプレイ API への実配線に差し替える。
const SAMPLE_SNAPSHOT: DagSnapshot = {
  run_id: 'sample-run',
  symbol: '7203',
  horizon_type: 'mid_term',
  status: 'done',
  started_at: '2026-06-01T08:50:00+09:00',
  finished_at: '2026-06-01T08:50:04+09:00',
  pick_id: 'sample-pick',
  stages: {
    collect: 'done',
    subscore: 'done',
    synthesis: 'done',
    llm_overlay: 'done',
    bracket: 'done',
    verify: 'done',
  },
};

const SAMPLE_EVENTS: TraceEvent[] = [
  {
    run_id: 'sample-run',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'collect',
    stage_status: 'done',
    stage_seq: 1,
    payload: { current_price: 3120.0, atr_14: 42.5 },
    event_at: '2026-06-01T08:50:00+09:00',
  },
  {
    run_id: 'sample-run',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'subscore',
    stage_status: 'done',
    stage_seq: 2,
    payload: { score_breakdown: { technical: 64, fundamental: 58 }, trend_score: 55 },
    event_at: '2026-06-01T08:50:01+09:00',
  },
  {
    run_id: 'sample-run',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'synthesis',
    stage_status: 'done',
    stage_seq: 3,
    payload: { composite_score: 62.4, concordance: 0.67, direction: 'bullish' },
    event_at: '2026-06-01T08:50:02+09:00',
  },
  {
    run_id: 'sample-run',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'llm_overlay',
    stage_status: 'done',
    stage_seq: 4,
    payload: { should_include: true, confidence_raw: 72, buy_price: 3122.0 },
    event_at: '2026-06-01T08:50:03+09:00',
  },
  {
    run_id: 'sample-run',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'bracket',
    stage_status: 'done',
    stage_seq: 5,
    payload: { entry: 3122.0, stop: 3040.0, target: 3260.0, capped_confidence: 72 },
    event_at: '2026-06-01T08:50:03+09:00',
  },
  {
    run_id: 'sample-run',
    pick_id: 'sample-pick',
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: '2026-06-01T08:50:04+09:00',
    status: 'done',
    stage: 'verify',
    stage_status: 'done',
    stage_seq: 6,
    payload: { confidence: 68, confidence_bucket: 'mid', win_rate: 0.58, n_filled: 34 },
    event_at: '2026-06-01T08:50:04+09:00',
  },
];

const SAMPLE_SOURCE_CONTRIBUTIONS = {
  technical: { weight_share: 0.41, contribution: 26.2, score: 64 },
  ml_prediction: { weight_share: 0.22, contribution: -4.8, score: 38 },
  fundamental: { weight_share: 0.24, contribution: 13.9, score: 58 },
  sentiment: { weight_share: 0.13, contribution: 6.5, score: 51 },
};

export default function StockDetailPage(): ReactNode {
  return (
    <PageShell title="銘柄詳細" phase="P6 / P8">
      <p>チャート（複数時間軸）+ 4 分析内訳 + AI 思考トレース（ライブ / リプレイ）。</p>

      <section aria-labelledby="pipeline-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="pipeline-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          AI 推論トレース（サンプル表示 — P6d でライブ配信へ差し替え）
        </h2>
        <StageDag snapshot={SAMPLE_SNAPSHOT} />
        <div className="pipeline-preview-grid">
          <ThinkingPanel events={SAMPLE_EVENTS} />
          <ShapBar sourceContributions={SAMPLE_SOURCE_CONTRIBUTIONS} />
        </div>
      </section>
    </PageShell>
  );
}
