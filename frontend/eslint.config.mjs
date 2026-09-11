import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

// eslint-config-next 16 は Flat Config を直接エクスポートする（Market Lens 踏襲）。
const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTypescript,
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
    // Service Worker は素の ES2017+ ブラウザスクリプト（self/importScripts 等の Worker
    // グローバルを使う）で Next.js のビルドを通らない静的配信ファイルのため、
    // アプリ本体（TypeScript strict）の lint 対象から外す。
    'public/**',
  ]),
]);

export default eslintConfig;
