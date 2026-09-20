import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { Caprasimo, Figtree } from 'next/font/google';
import { DisclaimerFooter } from '@/components/DisclaimerFooter';
import { Sidebar } from '@/components/layout/Sidebar';
import './globals.css';

// 見出し=Caprasimo・本文=Figtree（"Organic" デザインシステム採用フォント）。
// next/font はビルド時に自己ホスト化されるため外部リクエストが発生しない。
// 生成される CSS 変数は tokens.css の --font-display / --font-ui から参照する。
const caprasimo = Caprasimo({
  weight: '400',
  subsets: ['latin'],
  variable: '--font-heading-family',
  display: 'swap',
});
const figtree = Figtree({
  weight: ['400', '600', '700'],
  subsets: ['latin'],
  variable: '--font-body-family',
  display: 'swap',
});

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

const ICON_PROPS = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

const NAV = [
  {
    href: '/dashboard',
    label: 'ダッシュボード',
    icon: (
      <svg {...ICON_PROPS}>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </svg>
    ),
  },
  {
    href: '/stock-detail',
    label: '銘柄詳細',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M3 17l5-5 4 4 8-9" />
      </svg>
    ),
  },
  {
    href: '/portfolio',
    label: 'ポートフォリオ',
    icon: (
      <svg {...ICON_PROPS}>
        <rect x="3" y="7" width="18" height="13" rx="2" />
        <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      </svg>
    ),
  },
  {
    href: '/model-lab',
    label: 'モデルラボ',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M9 2v6.5L4 18a2 2 0 0 0 1.8 3h12.4a2 2 0 0 0 1.8-3l-5-9.5V2" />
        <path d="M9 2h6" />
      </svg>
    ),
  },
  {
    href: '/notifications',
    label: '通知センター',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M6 8a6 6 0 0 1 12 0c0 4 1.5 5.5 2 7H4c.5-1.5 2-3 2-7" />
        <path d="M10 21a2 2 0 0 0 4 0" />
      </svg>
    ),
  },
  {
    href: '/settings',
    label: '設定',
    icon: (
      <svg {...ICON_PROPS}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
];

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="ja" className={`${caprasimo.variable} ${figtree.variable}`}>
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
