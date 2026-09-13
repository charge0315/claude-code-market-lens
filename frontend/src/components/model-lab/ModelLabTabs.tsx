'use client';

import { useState, type ReactNode } from 'react';
import './model-lab.css';

// モデルラボの「かんたん」/「詳細」タブ切り替え（🆕 P14）。
// 初心者は学習トリガー中心の「かんたん」タブだけで完結し、champion/challenger 比較・
// PSI ドリフト・成長曲線等の既存の上級者向けセクションは「詳細」タブへ切り離す。
// 表示のたびに必ず「かんたん」から始める（ユーザー指示）。前回の選択を記憶して復元すると、
// 詳細タブを見た直後の再訪問で意図せず詳細が既定表示になってしまうため、永続化はしない。

type Tab = 'simple' | 'advanced';

export function ModelLabTabs({ simple, advanced }: { simple: ReactNode; advanced: ReactNode }): ReactNode {
  const [tab, setTab] = useState<Tab>('simple');

  return (
    <div className="model-lab-tabs">
      <div className="model-lab-tab-bar" role="tablist" aria-label="モデルラボの表示モード">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'simple'}
          className={tab === 'simple' ? 'is-active' : undefined}
          onClick={() => setTab('simple')}
        >
          かんたん
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'advanced'}
          className={tab === 'advanced' ? 'is-active' : undefined}
          onClick={() => setTab('advanced')}
        >
          詳細
        </button>
      </div>
      <div role="tabpanel" hidden={tab !== 'simple'}>
        {simple}
      </div>
      <div role="tabpanel" hidden={tab !== 'advanced'}>
        {advanced}
      </div>
    </div>
  );
}
