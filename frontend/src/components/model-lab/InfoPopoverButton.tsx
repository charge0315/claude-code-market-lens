'use client';

import { useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import './model-lab.css';

// 見出し横に置く「？」ボタン。押下でその見出しの詳しい説明をポップアップ表示する
// （🆕 P22、常時表示の一言説明文とは別に、掘り下げた説明を必要な人だけが開ける形にする）。

export function InfoPopoverButton({ title, children }: { title: string; children: ReactNode }): ReactNode {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="ml-info-btn"
        aria-label={`${title}の詳しい説明を見る`}
        onClick={() => setOpen(true)}
      >
        ?
      </button>
      {open && (
        <Modal title={title} onClose={() => setOpen(false)}>
          {children}
        </Modal>
      )}
    </>
  );
}
