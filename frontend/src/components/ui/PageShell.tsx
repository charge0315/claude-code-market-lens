import type { ReactNode } from 'react';

// 各画面の見出しと導入。
export function PageShell({
  title,
  badge,
  children,
}: {
  title: string;
  /** 見出し横に添える小さなラベル（例: 「自動学習ダッシュボード」）。任意。 */
  badge?: string;
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
      {children}
    </section>
  );
}
