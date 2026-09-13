'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchDrift, type DriftSnapshot } from '@/lib/api/registry';
import './model-lab.css';

// 特徴量分布ドリフト（PSI）の履歴。0.2 超（`DRIFT_PSI_THRESHOLD`）で drift_flag が立つ。
//
// 🔧 P19: 全履歴を並べた表だけでは「今どの特徴量が危ないか」が一目で分からないとの
// フィードバック（参考デザイン踏襲）を受け、特徴量ごとの最新スナップショットをバーで
// 表示する要約を表に追加した。しきい値は表示専用の目安ではなく実際の drift_flag
// （バックエンドの DRIFT_PSI_THRESHOLD 判定）をそのまま使う。

/** PSI バーの見た目上の最大値。実測がこれを超えても表示上は満タンで頭打ちにする。 */
const PSI_BAR_MAX = 0.4;

function latestPerFeature(snapshots: ReadonlyArray<DriftSnapshot>): DriftSnapshot[] {
  const latest = new Map<string, DriftSnapshot>();
  for (const s of snapshots) {
    const current = latest.get(s.feature_name);
    if (!current || s.computed_at > current.computed_at) {
      latest.set(s.feature_name, s);
    }
  }
  return [...latest.values()].sort((a, b) => b.psi - a.psi);
}

const COLUMNS: ReadonlyArray<Column<DriftSnapshot>> = [
  { key: 'feature_name', header: '特徴量' },
  { key: 'psi', header: 'PSI', numeric: true, render: (d) => d.psi.toFixed(4) },
  {
    key: 'drift_flag',
    header: '判定',
    render: (d) => (
      <span style={{ color: d.drift_flag ? 'var(--color-term-yellow)' : 'var(--color-text-muted)' }}>
        {d.drift_flag ? 'ドリフト検知' : '正常'}
      </span>
    ),
  },
  { key: 'computed_at', header: '計測日時' },
];

export function DriftPanel(): ReactNode {
  const [snapshots, setSnapshots] = useState<DriftSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDrift({ limit: 200 })
      .then(setSnapshots)
      .catch(() => setError('ドリフト履歴の取得に失敗しました'));
  }, []);

  const latest = latestPerFeature(snapshots);

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}

      {latest.length > 0 && (
        <>
          <p className="model-lab-subheading" style={{ marginTop: 0 }}>
            特徴量ごとの直近の状態
          </p>
          <div>
            {latest.map((d) => (
              <div className="ml-bar-row" key={d.feature_name}>
                <span>{d.feature_name}</span>
                <span className="ml-bar-track">
                  <span
                    className="ml-bar-fill"
                    style={{
                      width: `${Math.min(100, (d.psi / PSI_BAR_MAX) * 100)}%`,
                      background: d.drift_flag ? 'var(--color-accent)' : 'var(--color-accent-2)',
                    }}
                  />
                </span>
                <span className="ml-bar-value">{d.psi.toFixed(4)}</span>
                <span className={d.drift_flag ? 'ml-tag ml-tag-accent' : 'ml-tag ml-tag-accent-2'}>
                  {d.drift_flag ? '要再学習' : '安定'}
                </span>
              </div>
            ))}
          </div>
          <p className="model-lab-as-of" style={{ marginTop: 'var(--spacing-sm)' }}>
            PSI が既定のしきい値（`DRIFT_PSI_THRESHOLD`、既定 0.2）を超えると「要再学習」と判定されます。
          </p>
        </>
      )}

      <p className="model-lab-subheading">全履歴</p>
      <DataTable
        caption="特徴量分布ドリフト（PSI）履歴"
        columns={COLUMNS}
        rows={snapshots}
        rowKey={(d) => d.drift_id}
        emptyMessage="ドリフト計測はまだありません"
      />
    </div>
  );
}
