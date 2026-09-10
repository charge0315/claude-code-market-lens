import type { ReactNode } from 'react';

// 各画面の見出しと導入。P1 では枠のみ。中身は対応フェーズで実装する。
export function PageShell({
  title,
  phase,
  children,
}: {
  title: string;
  phase: string;
  children?: ReactNode;
}): ReactNode {
  return (
    <section aria-labelledby="page-heading">
      <h1 id="page-heading" style={{ fontSize: 'var(--font-size-2xl)', marginBottom: 'var(--spacing-sm)' }}>
        {title}
      </h1>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 'var(--spacing-xl)' }}>
        {phase} で実装予定
      </p>
      {children}
    </section>
  );
}
