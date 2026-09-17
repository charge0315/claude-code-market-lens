'use client';

import { useState, type ReactNode } from 'react';
import { PicksBoard } from '@/components/dashboard/PicksBoard';
import { ShadowPicksBoard } from '@/components/dashboard/ShadowPicksBoard';
import { useOfficialProviderLabel, useShadowProviderLabels } from '@/lib/llmProviderLabels';
import './dashboard.css';

// 公式パイプラインとシャドウ（challenger LLM、複数併用可）のピックを混在させず、
// エンジンごとに切り替えて表示する（ユーザー指示）。

type Engine = 'official' | 'shadow';

export function AiPicksSection(): ReactNode {
  const [engine, setEngine] = useState<Engine>('official');
  const officialLabel = useOfficialProviderLabel('stock_pick');
  const shadowLabels = useShadowProviderLabels('stock_pick');
  const shadowTabLabel = shadowLabels.length > 0 ? `${shadowLabels.join('・')}（比較）` : 'シャドウ（比較）';

  return (
    <div>
      <div className="picks-board-tabs ai-engine-tabs" role="group" aria-label="AIエンジン">
        <button
          type="button"
          className={engine === 'official' ? 'is-active' : undefined}
          aria-pressed={engine === 'official'}
          onClick={() => setEngine('official')}
        >
          {officialLabel}
        </button>
        <button
          type="button"
          className={engine === 'shadow' ? 'is-active' : undefined}
          aria-pressed={engine === 'shadow'}
          onClick={() => setEngine('shadow')}
        >
          {shadowTabLabel}
        </button>
      </div>
      {engine === 'official' ? <PicksBoard /> : <ShadowPicksBoard />}
    </div>
  );
}
