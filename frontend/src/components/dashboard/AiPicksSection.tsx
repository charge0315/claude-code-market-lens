'use client';

import { useState, type ReactNode } from 'react';
import { GeminiPicksBoard } from '@/components/dashboard/GeminiPicksBoard';
import { PicksBoard } from '@/components/dashboard/PicksBoard';
import './dashboard.css';

// Claude（公式パイプライン）と Gemini（challenger LLM）のピックを混在させず、
// エンジンごとに切り替えて表示する（🆕 P25、ユーザー指示）。

type Engine = 'claude' | 'gemini';

export function AiPicksSection(): ReactNode {
  const [engine, setEngine] = useState<Engine>('claude');

  return (
    <div>
      <div className="picks-board-tabs ai-engine-tabs" role="group" aria-label="AIエンジン">
        <button type="button" className={engine === 'claude' ? 'is-active' : undefined} aria-pressed={engine === 'claude'} onClick={() => setEngine('claude')}>
          Claude（公式）
        </button>
        <button type="button" className={engine === 'gemini' ? 'is-active' : undefined} aria-pressed={engine === 'gemini'} onClick={() => setEngine('gemini')}>
          Gemini（比較）
        </button>
      </div>
      {engine === 'claude' ? <PicksBoard /> : <GeminiPicksBoard />}
    </div>
  );
}
