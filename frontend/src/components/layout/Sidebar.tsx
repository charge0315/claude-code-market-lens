'use client';

import { useEffect, useState, type ReactNode } from 'react';
import './sidebar.css';

// 全ページ共通のメインナビゲーション。768px 以下ではハンバーガートグルで
// オフキャンバス表示に切り替える（P8、モバイルで固定 220px 幅が画面を圧迫し
// 横スクロールを起こしていた既存バグの修正 — `getBoundingClientRect` による実機確認で発覚）。

interface NavItem {
  href: string;
  label: string;
}

export function Sidebar({ items }: { items: ReadonlyArray<NavItem> }): ReactNode {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="app-sidebar-toggle"
        aria-label={open ? 'ナビゲーションを閉じる' : 'ナビゲーションを開く'}
        aria-expanded={open}
        aria-controls="app-sidebar"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">{open ? '✕' : '☰'}</span>
      </button>

      <div
        className={open ? 'app-sidebar-backdrop is-open' : 'app-sidebar-backdrop'}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      <aside
        id="app-sidebar"
        aria-label="メインナビゲーション"
        className={open ? 'app-sidebar is-open' : 'app-sidebar'}
      >
        <div className="app-sidebar-brand">ALPHA FORGE</div>
        <nav>
          <ul className="app-sidebar-nav">
            {items.map((item) => (
              <li key={item.href}>
                <a href={item.href} onClick={() => setOpen(false)}>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
    </>
  );
}
