// クライアント側で蓄積した TraceEvent 列から DagSnapshot を導出する純関数。
// バックエンド `services/inference/snapshot.build_snapshot` と同じロジック
// （run が running のときは、最後に完了したステージの次を推定 running として見せる）。

import { STAGE_ORDER, type DagSnapshot, type StageName, type StageStatus, type TraceEvent } from './types';

export function deriveSnapshot(runId: string, events: readonly TraceEvent[]): DagSnapshot {
  const stages = Object.fromEntries(STAGE_ORDER.map((s) => [s, 'pending'])) as Record<StageName, StageStatus>;
  for (const event of events) {
    if ((STAGE_ORDER as readonly string[]).includes(event.stage)) {
      stages[event.stage] = event.stage_status;
    }
  }

  if (events.length === 0) {
    return {
      run_id: runId,
      symbol: null,
      horizon_type: null,
      status: 'pending',
      started_at: null,
      finished_at: null,
      pick_id: null,
      stages,
    };
  }

  const last = events[events.length - 1];
  if (last.status === 'running') {
    const idx = STAGE_ORDER.indexOf(last.stage);
    const next = STAGE_ORDER[idx + 1];
    if (next) stages[next] = 'running';
  }

  return {
    run_id: runId,
    symbol: last.symbol,
    horizon_type: last.horizon_type,
    status: last.status,
    started_at: last.started_at,
    finished_at: last.finished_at,
    pick_id: last.pick_id,
    stages,
  };
}
