'use client';

import { useSyncExternalStore, type ReactNode } from 'react';
import './model-lab.css';

// モデルラボの「かんたん」/「詳細」タブ切り替え（🆕 P14）。
// 初心者は学習トリガー中心の「かんたん」タブだけで完結し、champion/challenger 比較・
// PSI ドリフト・成長曲線等の既存の上級者向けセクションは「詳細」タブへ切り離す。
// 選択状態は localStorage に保存し、次回訪問時も同じタブを開く（既定は「かんたん」）。
//
// localStorage は SSR 時に存在しないため、`useEffect` での事後 setState ではなく
// `useSyncExternalStore` で購読する（サーバースナップショットは常に既定値 'simple'、
// クライアントでは localStorage の実値を返す — React 公式が推奨する外部ストア購読パターン）。

type Tab = 'simple' | 'advanced';

const STORAGE_KEY = 'alpha-forge:model-lab-tab';
const listeners = new Set<() => void>();

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function getSnapshot(): Tab {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'advanced' ? 'advanced' : 'simple';
  } catch {
    return 'simple';
  }
}

function getServerSnapshot(): Tab {
  return 'simple';
}

function setStoredTab(next: Tab): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // localStorage が使えない環境（プライベートモード等）でもタブ切り替え自体は続行する。
  }
  listeners.forEach((callback) => callback());
}

export function ModelLabTabs({ simple, advanced }: { simple: ReactNode; advanced: ReactNode }): ReactNode {
  const tab = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <div className="model-lab-tabs">
      <div className="model-lab-tab-bar" role="tablist" aria-label="モデルラボの表示モード">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'simple'}
          className={tab === 'simple' ? 'is-active' : undefined}
          onClick={() => setStoredTab('simple')}
        >
          かんたん
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'advanced'}
          className={tab === 'advanced' ? 'is-active' : undefined}
          onClick={() => setStoredTab('advanced')}
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
