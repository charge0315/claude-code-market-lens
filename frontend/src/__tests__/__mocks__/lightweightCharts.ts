// lightweight-charts のテスト用モック（jsdom は canvas を持たない）。
export const createChart = () => ({
  addCandlestickSeries: () => ({ setData: jest.fn() }),
  addHistogramSeries: () => ({ setData: jest.fn() }),
  addLineSeries: () => ({ setData: jest.fn() }),
  applyOptions: jest.fn(),
  timeScale: () => ({ fitContent: jest.fn() }),
  remove: jest.fn(),
});
export const ColorType = { Solid: 'solid' } as const;
