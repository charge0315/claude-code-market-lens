import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { DisclaimerFooter } from '@/components/DisclaimerFooter';
import './globals.css';

export const metadata: Metadata = {
  title: 'Alpha Forge',
  description:
    '日本株の AI 銘柄ピック（中長期 / 短期）と継続学習ループ。出力は分析結果・参考情報であり投資助言ではない。',
};

const NAV = [
  { href: '/dashboard', label: 'ダッシュボード' },
  { href: '/stock-detail', label: '銘柄詳細' },
  { href: '/portfolio', label: 'ポートフォリオ' },
  { href: '/model-lab', label: 'モデルラボ' },
  { href: '/notifications', label: '通知センター' },
];

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="ja">
      <body>
        <div style={{ display: 'flex', minHeight: '100vh' }}>
          <aside
            aria-label="メインナビゲーション"
            style={{
              width: 'var(--sidebar-width)',
              borderRight: '1px solid var(--color-border)',
              background: 'var(--color-bg-secondary)',
              padding: 'var(--spacing-lg)',
            }}
          >
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'var(--font-size-xl)',
                letterSpacing: '0.04em',
                marginBottom: 'var(--spacing-xl)',
              }}
            >
              ALPHA FORGE
            </div>
            <nav>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-xs)' }}>
                {NAV.map((item) => (
                  <li key={item.href}>
                    <a href={item.href} style={{ display: 'block', padding: 'var(--spacing-sm)' }}>
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          </aside>
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            {/* flex アイテムは既定で min-width: auto のため、内側に横幅の大きい要素（データ
                テーブル等）があるとページ全体が横スクロールしてしまう（flexbox の既知の罠）。
                min-width: 0 でコンテンツ幅ではなく親の残り幅に収める。 */}
            <main style={{ flex: 1, minWidth: 0, padding: 'var(--spacing-xl)' }}>{children}</main>
            <DisclaimerFooter />
          </div>
        </div>
      </body>
    </html>
  );
}
