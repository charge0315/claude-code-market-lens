import type { ReactNode } from 'react';

// 各画面の見出しと導入。`phase` は未実装フェーズの案内表示用（🔧 P13: 実装済みの画面
// （ダッシュボード等）では省略してよいよう任意化した — 完成済み機能に「実装予定」の
// 案内を出し続けるのは実態と乖離するため）。
export function PageShell({
  title,
  badge,
  phase,
  children,
}: {
  title: string;
  /** 見出し横に添える小さなラベル（例: 「自動学習ダッシュボード」）。任意。 */
  badge?: string;
  phase?: string;
  children?: ReactNode;
}): ReactNode {
  return (
    <section aria-labelledby="page-heading">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-md)', marginBottom: 'var(--spacing-sm)' }}>
        <h1 id="page-heading" style={{ fontSize: 'var(--font-size-2xl)', margin: 0 }}>
          {title}
        </h1>
        {badge && (
          <span
            style={{
              fontSize: 'var(--font-size-xs)',
              color: 'var(--color-text-secondary)',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-full)',
              padding: '3px var(--spacing-md)',
            }}
          >
            {badge}
          </span>
        )}
      </div>
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
