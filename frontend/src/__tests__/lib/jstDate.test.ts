import { todayJst } from '@/lib/jstDate';

describe('todayJst', () => {
  it('YYYY-MM-DD 形式の文字列を返す', () => {
    expect(todayJst()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('ブラウザのローカルタイムゾーンに関わらず Asia/Tokyo の日付を返す', () => {
    // 例: UTC 2026-09-13T20:00:00Z は JST では 2026-09-14 05:00 になる。
    jest.useFakeTimers().setSystemTime(new Date('2026-09-13T20:00:00Z'));
    expect(todayJst()).toBe('2026-09-14');
    jest.useRealTimers();
  });
});
