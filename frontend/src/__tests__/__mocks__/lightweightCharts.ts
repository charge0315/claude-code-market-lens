// lightweight-charts のテスト用モック（jsdom は canvas を持たない）。
// v5 の addSeries(SeriesDefinition, options) 形式・v4 系の addXxxSeries() 形式の両方を
// カバーする（呼び出し側がどちらの API 形状で実装されていても壊れないように）。
export const createChart = () => ({
  addSeries: () => ({ setData: jest.fn() }),
  addCandlestickSeries: () => ({ setData: jest.fn() }),
  addHistogramSeries: () => ({ setData: jest.fn() }),
  addLineSeries: () => ({ setData: jest.fn() }),
  applyOptions: jest.fn(),
  timeScale: () => ({ fitContent: jest.fn() }),
  remove: jest.fn(),
});
export const ColorType = { Solid: 'solid' } as const;
// v5 の addSeries 第一引数（シリーズ種別定義）。実体は使わずダミーで足りる。
export const CandlestickSeries = 'CandlestickSeries';
export const LineSeries = 'LineSeries';
export const HistogramSeries = 'HistogramSeries';
