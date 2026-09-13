import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { DisclaimerFooter } from '@/components/DisclaimerFooter';
import { Sidebar } from '@/components/layout/Sidebar';
import './globals.css';

export const metadata: Metadata = {
  title: 'Alpha Forge',
  description:
    '日本株の AI 銘柄ピック（中長期 / 短期）と継続学習ループ。出力は分析結果・参考情報であり投資助言ではない。',
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: "/favicon-180.png",
  },
};

const NAV = [
  { href: '/dashboard', label: 'ダッシュボード' },
  { href: '/stock-detail', label: '銘柄詳細' },
  { href: '/portfolio', label: 'ポートフォリオ' },
  { href: '/model-lab', label: 'モデルラボ' },
  { href: '/notifications', label: '通知センター' },
  { href: '/settings', label: '設定' },
];

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="ja">
      <body>
        <div style={{ display: 'flex', minHeight: '100vh' }}>
          <Sidebar items={NAV} />
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
