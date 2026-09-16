'use client';

import { useState, type ReactNode } from 'react';
import { PicksBoard } from '@/components/dashboard/PicksBoard';
import { ShadowPicksBoard } from '@/components/dashboard/ShadowPicksBoard';
import './dashboard.css';

// 公式パイプラインとシャドウ（challenger LLM、複数併用可）のピックを混在させず、
// エンジンごとに切り替えて表示する（ユーザー指示）。

type Engine = 'official' | 'shadow';

export function AiPicksSection(): ReactNode {
  const [engine, setEngine] = useState<Engine>('official');

  return (
    <div>
      <div className="picks-board-tabs ai-engine-tabs" role="group" aria-label="AIエンジン">
        <button
          type="button"
          className={engine === 'official' ? 'is-active' : undefined}
          aria-pressed={engine === 'official'}
          onClick={() => setEngine('official')}
        >
          公式
        </button>
        <button
          type="button"
          className={engine === 'shadow' ? 'is-active' : undefined}
          aria-pressed={engine === 'shadow'}
          onClick={() => setEngine('shadow')}
        >
          シャドウ（比較）
        </button>
      </div>
      {engine === 'official' ? <PicksBoard /> : <ShadowPicksBoard />}
    </div>
  );
}
