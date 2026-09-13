import { expectedReturnPct, formatYen, sparkColor, truncate } from '@/components/dashboard/pickDisplay';

describe('pickDisplay helpers', () => {
  it('formatYen: 円マーク・カンマ区切りで整形する', () => {
    expect(formatYen(3050)).toBe('¥3,050');
    expect(formatYen(1000000)).toBe('¥1,000,000');
  });

  it('expectedReturnPct: entry=0では0を返す（ゼロ除算回避）', () => {
    expect(expectedReturnPct(0, 100)).toBe(0);
    expect(expectedReturnPct(1000, 1100)).toBeCloseTo(10);
  });

  it('truncate: 上限を超えたら…を付けて切り詰める', () => {
    expect(truncate('short')).toBe('short');
    expect(truncate('a'.repeat(60))).toBe(`${'a'.repeat(50)}…`);
  });

  it('sparkColor: 始点<終点で上昇色、始点>終点で下降色', () => {
    expect(sparkColor([100, 90, 110])).toBe('var(--color-gain)');
    expect(sparkColor([100, 90])).toBe('var(--color-loss)');
    expect(sparkColor([100, 100])).toBe('var(--color-flat)');
    expect(sparkColor([100])).toBe('var(--color-flat)');
  });
});
