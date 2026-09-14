import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

// @media の max-width は 640 / 768 / 900 / 1280 の 4 段のみ（プロ端末規約）。
// 場当たりに breakpoint を増やすと同じ幅で別々の崩れ方をするページが生まれる。
const ALLOWED = new Set(['640px', '768px', '900px', '1280px']);
const SRC = join(process.cwd(), 'src');

// CI は Node.js 20 固定のため `fs.globSync`（Node 22+）は使えない。
// `readdirSync(..., { recursive: true })` は Node 20.1+ で利用可能なのでこちらを使う。
function findCssFiles(dir: string): string[] {
  return readdirSync(dir, { recursive: true })
    .map((p) => p.toString())
    .filter((p) => p.endsWith('.css'))
    .map((p) => join(dir, p));
}

describe('CSS ブレークポイント規約', () => {
  it('max-width は許可された 4 段のみ', () => {
    const cssFiles = findCssFiles(SRC);
    const violations: string[] = [];
    for (const file of cssFiles) {
      const content = readFileSync(file, 'utf8');
      for (const match of content.matchAll(/max-width:\s*([0-9]+px)/g)) {
        if (!ALLOWED.has(match[1])) violations.push(`${file}: ${match[1]}`);
      }
    }
    expect(violations).toEqual([]);
  });
});
