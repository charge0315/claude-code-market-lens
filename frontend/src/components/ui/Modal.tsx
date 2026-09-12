'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import './modal.css';

// 汎用ポップアップ（ナレッジベースノート表示・根拠詳細表示 で共用）。
// backdrop クリック・Escape キーで閉じる。フォーカスを閉じるボタンへ当てて a11y を確保する。
// `variant="panel"`（🆕 P13）は右からスライドインする詳細パネル表示用（ピック詳細等、
// 参照デザイン準拠）。既定 `"center"` は既存呼び出し元と完全互換（挙動変更なし）。

export function Modal({
  title,
  onClose,
  children,
  variant = 'center',
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  variant?: 'center' | 'panel';
}): ReactNode {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const isPanel = variant === 'panel';

  return (
    <div className={isPanel ? 'modal-backdrop is-panel' : 'modal-backdrop'} onClick={onClose}>
      <div
        className={isPanel ? 'modal-content is-panel' : 'modal-content'}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="modal-title" className="modal-title">
            {title}
          </h2>
          <button type="button" ref={closeButtonRef} className="modal-close" onClick={onClose} aria-label="閉じる">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
