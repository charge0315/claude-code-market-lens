'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchPitCoverage, type PitCoverageStatus } from '@/lib/api/registry';
import './model-lab.css';

// PIT（point-in-time）特徴量スナップショットの収集進捗（🆕 P29）。
//
// Obsidian Vaultに補完された銘柄のニュース・決算情報をML学習（断面プールモデル）へ
// 組み込むには、Vault frontmatter（「現在値」の上書きファイル）を過去の学習行へそのまま
// 結合すると未来情報が漏れる（lookahead bias）ため、実装日から前向きに日次スナップショットを
// 積み上げる必要がある（`plans/03_システム設計` §1.8/§3.7）。本パネルはその収集進捗を表示する。

export function PitCoveragePanel(): ReactNode {
  const [status, setStatus] = useState<PitCoverageStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPitCoverage()
      .then(setStatus)
      .catch(() => setError('PIT特徴量の収集進捗の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (!status) return null;

  return (
    <div className="model-lab-panel">
      <p className="model-lab-as-of" style={{ marginTop: 0 }}>
        学習パネルへの投入は{' '}
        <span className={status.features_enabled ? 'ml-tag ml-tag-accent-2' : 'ml-tag ml-tag-neutral'}>
          {status.features_enabled ? '有効' : '未有効（PIT_FEATURES_ENABLED=false）'}
        </span>
        。グループごとに必要な収集営業日数に達すると、断面プールモデルの学習特徴量へ自動的に
        組み込まれます（欠損時は0埋めではなく「未収集」として扱われます）。
      </p>
      <div>
        {status.groups.map((g) => (
          <div className="ml-bar-row" key={g.group}>
            <span>{g.label}</span>
            <span className="ml-bar-track">
              <span
                className="ml-bar-fill"
                style={{
                  width: `${Math.min(100, (g.collected_days / Math.max(1, g.min_coverage_days)) * 100)}%`,
                  background: g.ready ? 'var(--color-accent-2)' : 'var(--color-accent)',
                }}
              />
            </span>
            <span className="ml-bar-value">
              {g.collected_days} / {g.min_coverage_days} 営業日
            </span>
            <span className={g.ready ? 'ml-tag ml-tag-accent-2' : 'ml-tag ml-tag-neutral'}>
              {g.ready ? '投入可' : `あと${g.remaining_days}営業日`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
