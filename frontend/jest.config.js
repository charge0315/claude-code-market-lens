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
    '!src/proxy.ts',
    '!src/__tests__/**',
  ],
  // P1 雛形時点の下限ガード。画面実装が進む P8 で実測に合わせて引き上げる。
  coverageThreshold: {
    global: { statements: 60, branches: 60, functions: 60, lines: 60 },
  },
  modulePathIgnorePatterns: ['<rootDir>/.next/'],
};

module.exports = config;
