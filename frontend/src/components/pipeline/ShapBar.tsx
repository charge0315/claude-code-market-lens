import type { ReactNode } from 'react';
import { FACTOR_LABELS, type SourceContribution } from '@/lib/pipeline/types';
import './pipeline.css';

// synthesis ステージの source_contributions（CL-1）を寄与度バーで表示する。
// 実 ML の SHAP 値ではなく合成スコアへの寄与（weight_share × score）だが、
// 「どのファクターが判断を動かしたか」という目的は同じため、この可視化を代用する
// （`plans/04_タスクリスト.md` P6 の未対応項目「サブスコアの SHAP 相当寄与」参照）。

interface ShapBarProps {
  sourceContributions: Readonly<Record<string, SourceContribution>>;
}

export function ShapBar({ sourceContributions }: ShapBarProps): ReactNode {
  const entries = Object.entries(sourceContributions);
  if (entries.length === 0) {
    return <p className="shap-bar-empty">寄与度データがありません</p>;
  }
  const maxAbs = Math.max(1, ...entries.map(([, v]) => Math.abs(v.contribution)));

  return (
    <ul className="shap-bar" aria-label="各ファクターの合成スコアへの寄与度">
      {entries.map(([factor, v]) => (
        <li key={factor} className="shap-bar-row">
          <span className="shap-bar-label">{FACTOR_LABELS[factor] ?? factor}</span>
          <span className="shap-bar-track">
            <span
              className={`shap-bar-fill${v.contribution < 0 ? ' shap-bar-fill--negative' : ''}`}
              style={{ width: `${Math.min(100, (Math.abs(v.contribution) / maxAbs) * 100)}%` }}
            />
          </span>
          <span className="shap-bar-value num">{v.contribution.toFixed(1)}</span>
        </li>
      ))}
    </ul>
  );
}
