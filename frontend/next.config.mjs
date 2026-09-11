// バックエンドのプロキシ先はサーバー側でのみ参照する（ブラウザに露出させない）。
// Alpha Forge の backend は 8002（Market Lens 8001 と非衝突）。
const backendUrl = process.env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8002';

// クリックジャッキング・MIME スニッフィング対策の基本ヘッダー。
// nonce ベース CSP は src/middleware.ts がリクエストごとに付与する。
const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Next.js の AI エージェント検出による AGENTS.md/CLAUDE.md 自動生成を無効化
  // （このリポジトリは CLAUDE.md を自前管理する）。
  agentRules: false,
  output: 'standalone',
  outputFileTracingRoot: import.meta.dirname,
  // Playwright（e2e/playwright.config.ts）は baseURL に 127.0.0.1 を使う。Next.js 16 の dev
  // サーバーは既定で localhost 以外からの HMR 接続を安全のためブロックし、ブロックされると
  // クライアント側の再接続ループで React のハイドレーションが実質的に止まる（P6d の E2E で
  // 「ボタンを押しても aria-pressed が変わらない」という形で発覚した）。
  allowedDevOrigins: ['127.0.0.1'],
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${backendUrl}/api/:path*` },
      // WS はプレフィックス無しの /ws/notifications（`routers/notify.py` 参照）。Next.js の
      // rewrites は外部 destination への WebSocket アップグレードも透過する。
      { source: '/ws/:path*', destination: `${backendUrl}/ws/:path*` },
    ];
  },
};

export default nextConfig;
