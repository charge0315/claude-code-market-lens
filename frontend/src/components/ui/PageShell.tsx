import type { ReactNode } from 'react';

// 各画面の見出しと導入。`phase` は未実装フェーズの案内表示用（🔧 P13: 実装済みの画面
// （ダッシュボード等）では省略してよいよう任意化した — 完成済み機能に「実装予定」の
// 案内を出し続けるのは実態と乖離するため）。
export function PageShell({
  title,
  phase,
  children,
}: {
  title: string;
  phase?: string;
  children?: ReactNode;
}): ReactNode {
  return (
    <section aria-labelledby="page-heading">
      <h1 id="page-heading" style={{ fontSize: 'var(--font-size-2xl)', marginBottom: 'var(--spacing-sm)' }}>
        {title}
      </h1>
      {phase && (
        <p
          style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 'var(--spacing-xl)' }}
        >
          {phase} で実装予定
        </p>
      )}
      {children}
    </section>
  );
}
