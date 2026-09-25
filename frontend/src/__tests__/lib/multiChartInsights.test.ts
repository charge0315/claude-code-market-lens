import type { OhlcBar } from '@/lib/api/stock';
import { analyzeBars, summarizeTimeframes, type TimeframeInsight } from '@/lib/multiChartInsights';

// 終値の列から高値=終値+5・安値=終値-5 のバーを組み立てる（レンジ位置の計算を読みやすくするため）。
function barsFromCloses(closes: number[]): OhlcBar[] {
  return closes.map((close, i) => ({ time: i, open: close, high: close + 5, low: close - 5, close, volume: 1000 }));
}

function linear(start: number, step: number, count: number): number[] {
  return Array.from({ length: count }, (_, i) => start + step * i);
}

function insight(overrides: Partial<TimeframeInsight>): TimeframeInsight {
  return { changePct: 0, trend: 'range', rangePosition: 'middle', rangePct: 50, ...overrides };
}

describe('analyzeBars', () => {
  it('本数が足りないときは null を返す', () => {
    expect(analyzeBars(barsFromCloses(linear(100, 1, 10)))).toBeNull();
  });

  it('一貫して上昇する系列は上昇基調・高値圏と判定する', () => {
    const result = analyzeBars(barsFromCloses(linear(100, 1, 60)));

    expect(result).not.toBeNull();
    expect(result?.trend).toBe('up');
    expect(result?.rangePosition).toBe('high');
    expect(result?.changePct).toBeCloseTo(59, 5);
  });

  it('一貫して下落する系列は下降基調・安値圏と判定する', () => {
    const result = analyzeBars(barsFromCloses(linear(200, -1, 60)));

    expect(result?.trend).toBe('down');
    expect(result?.rangePosition).toBe('low');
    expect(result?.changePct).toBeLessThan(0);
  });

  it('上昇後に移動平均を割り込んだ系列は方向感なし（もみ合い）と判定する', () => {
    // 平均線はまだ上向きだが終値が平均線を下回る = 上昇基調・下降基調のどちらの条件も満たさない。
    const closes = [...linear(100, 1, 50), 120];
    const result = analyzeBars(barsFromCloses(closes));

    expect(result?.trend).toBe('range');
  });
});

describe('summarizeTimeframes', () => {
  it('全時間軸が上昇基調ならそろって上昇している旨を返す', () => {
    const lines = summarizeTimeframes({
      short: insight({ trend: 'up' }),
      mid: insight({ trend: 'up' }),
      long: insight({ trend: 'up' }),
    });

    expect(lines[0]).toContain('すべての時間軸で上昇基調');
  });

  it('全時間軸が下降基調ならそろって下降している旨を返す', () => {
    const lines = summarizeTimeframes({
      short: insight({ trend: 'down' }),
      mid: insight({ trend: 'down' }),
      long: insight({ trend: 'down' }),
    });

    expect(lines[0]).toContain('すべての時間軸で下降基調');
  });

  it('日足が上昇・短期足が下降なら上昇基調の中の調整と説明する', () => {
    const lines = summarizeTimeframes({ short: insight({ trend: 'down' }), long: insight({ trend: 'up' }) });

    expect(lines[0]).toContain('短期足では下押し');
  });

  it('日足が下降・短期足が上昇なら下降基調の中の反発と説明する', () => {
    const lines = summarizeTimeframes({ short: insight({ trend: 'up' }), long: insight({ trend: 'down' }) });

    expect(lines[0]).toContain('短期足では反発');
  });

  it('日足のレンジ位置が高値圏・安値圏ならその旨を添える', () => {
    const high = summarizeTimeframes({ long: insight({ rangePosition: 'high', rangePct: 92 }) });
    const low = summarizeTimeframes({ long: insight({ rangePosition: 'low', rangePct: 8 }) });

    expect(high.some((l) => l.includes('高値圏'))).toBe(true);
    expect(low.some((l) => l.includes('安値圏'))).toBe(true);
  });

  it('判定材料が無ければ空配列を返す', () => {
    expect(summarizeTimeframes({})).toEqual([]);
  });
});
