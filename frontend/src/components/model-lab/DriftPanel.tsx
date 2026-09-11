'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchDrift, type DriftSnapshot } from '@/lib/api/registry';
import './model-lab.css';

// 特徴量分布ドリフト（PSI）の履歴。0.2 超（`DRIFT_PSI_THRESHOLD`）で drift_flag が立つ。

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

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}
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
