/** @type {import('jest').Config} */
const config = {
  coverageProvider: 'v8',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    // css/画像モックは '@/...' より先に置く（jest は先にマッチしたパターンで確定する）。
    '\\.(css|scss|sass)$': '<rootDir>/src/__tests__/__mocks__/styleMock.ts',
    '\\.(png|jpg|jpeg|gif|svg|webp)$': '<rootDir>/src/__tests__/__mocks__/fileMock.ts',
    '^@/(.*)$': '<rootDir>/src/$1',
    '^next/navigation$': '<rootDir>/src/__tests__/__mocks__/nextNavigation.ts',
    '^next/link$': '<rootDir>/src/__tests__/__mocks__/nextLink.tsx',
    '^lightweight-charts$': '<rootDir>/src/__tests__/__mocks__/lightweightCharts.ts',
  },
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', { tsconfig: { jsx: 'react-jsx' } }],
  },
  testMatch: ['**/src/__tests__/**/*.test.ts', '**/src/__tests__/**/*.test.tsx'],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/**/layout.tsx',
    // 画面ページ（app/**/page.tsx）は各コンポーネントへ委譲するだけの配線のみで
    // ロジックを持たない。実体は components/ 側のユニットテストと e2e/ の画面単位
    // テストでカバーする方針にした（layout.tsx と同じ扱い）。
    '!src/app/**/page.tsx',
    '!src/proxy.ts',
    '!src/__tests__/**',
  ],
  // P8 で実測（statements/lines ~89%, branches ~83%, functions ~71%）に合わせて引き上げ。
  // 実測ちょうどにはせず、テスト追加の余地を残す少し保守的な下限にする。
  coverageThreshold: {
    global: { statements: 85, branches: 75, functions: 65, lines: 85 },
  },
  modulePathIgnorePatterns: ['<rootDir>/.next/'],
};

module.exports = config;
