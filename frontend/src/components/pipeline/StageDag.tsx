import type { ReactNode } from 'react';
import { STAGE_LABELS, STAGE_ORDER, type DagSnapshot } from '@/lib/pipeline/types';
import './pipeline.css';

// 推論オーケストレータ（stage DAG）の進行状況を横並びノードで表示する。
// pending/running/done/failed は tokens.css の --color-stage-* を必ず経由する。

interface StageDagProps {
  snapshot: Pick<DagSnapshot, 'stages' | 'status'>;
}

const ICONS: Record<string, string> = { pending: '', running: '', done: '✓', failed: '✕' };

export function StageDag({ snapshot }: StageDagProps): ReactNode {
  return (
    <ol className="stage-dag" aria-label="AI 推論ステージの進行状況">
      {STAGE_ORDER.map((stage, i) => {
        const status = snapshot.stages[stage];
        return (
          <li key={stage} className="stage-dag-item">
            <div
              className={`stage-node stage-node--${status}`}
              aria-current={status === 'running' ? 'step' : undefined}
            >
              <span className="stage-node-dot" aria-hidden="true">
                {ICONS[status]}
              </span>
              <span className="stage-node-label">{STAGE_LABELS[stage]}</span>
              <span className="visually-hidden">
                {STAGE_LABELS[stage]}:{' '}
                {status === 'pending' ? '未着手' : status === 'running' ? '実行中' : status === 'done' ? '完了' : '失敗'}
              </span>
            </div>
            {i < STAGE_ORDER.length - 1 && (
              <span
                className={`stage-dag-connector${status === 'done' ? ' stage-dag-connector--filled' : ''}`}
                aria-hidden="true"
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
