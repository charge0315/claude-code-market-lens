import { deriveSnapshot } from '@/lib/pipeline/deriveSnapshot';
import { STAGE_ORDER, type TraceEvent } from '@/lib/pipeline/types';

function event(overrides: Partial<TraceEvent>): TraceEvent {
  return {
    run_id: 'run-1',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'collect',
    stage_status: 'done',
    stage_seq: 1,
    payload: {},
    event_at: '2026-06-01T08:50:01+09:00',
    ...overrides,
  };
}

describe('deriveSnapshot', () => {
  it('イベントが無ければ全ステージ pending を返す', () => {
    const snap = deriveSnapshot('run-1', []);
    expect(snap.status).toBe('pending');
    expect(Object.values(snap.stages).every((s) => s === 'pending')).toBe(true);
  });

  it('running 中は次のステージを推定 running にする', () => {
    const snap = deriveSnapshot('run-1', [
      event({ stage: 'collect', stage_status: 'done' }),
      event({ stage: 'subscore', stage_status: 'done', stage_seq: 2 }),
    ]);
    expect(snap.stages.collect).toBe('done');
    expect(snap.stages.subscore).toBe('done');
    expect(snap.stages.synthesis).toBe('running');
    expect(snap.stages.llm_overlay).toBe('pending');
  });

  it('完了した run は全ステージ done で running 推定をしない', () => {
    const events = STAGE_ORDER.map((stage, i) =>
      event({ stage, stage_status: 'done', stage_seq: i + 1, status: i === STAGE_ORDER.length - 1 ? 'done' : 'running' }),
    );
    const snap = deriveSnapshot('run-1', events);
    expect(Object.values(snap.stages).every((s) => s === 'done')).toBe(true);
    expect(snap.status).toBe('done');
  });

  it('失敗した run は以降のステージへ running 推定をしない', () => {
    const snap = deriveSnapshot('run-1', [
      event({ stage: 'collect', stage_status: 'done' }),
      event({ stage: 'subscore', stage_status: 'failed', stage_seq: 2, status: 'rejected' }),
    ]);
    expect(snap.stages.subscore).toBe('failed');
    expect(snap.stages.synthesis).toBe('pending');
    expect(snap.status).toBe('rejected');
  });
});
