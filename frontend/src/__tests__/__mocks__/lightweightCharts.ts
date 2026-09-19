// lightweight-charts のテスト用モック（jsdom は canvas を持たない）。
// v5 の addSeries(SeriesDefinition, options) 形式・v4 系の addXxxSeries() 形式の両方を
// カバーする（呼び出し側がどちらの API 形状で実装されていても壊れないように）。
// 🆕 crosshairMove の購読ハンドラを保持し、テストから直接発火できるようにする
// （jsdom はマウスイベントで実際の crosshair 移動を再現できないための代替）。
let crosshairHandlers: Array<(param: unknown) => void> = [];

export const createChart = () => ({
  addSeries: () => ({ setData: jest.fn() }),
  addCandlestickSeries: () => ({ setData: jest.fn() }),
  addHistogramSeries: () => ({ setData: jest.fn() }),
  addLineSeries: () => ({ setData: jest.fn() }),
  applyOptions: jest.fn(),
  timeScale: () => ({ fitContent: jest.fn() }),
  subscribeCrosshairMove: (handler: (param: unknown) => void) => {
    crosshairHandlers.push(handler);
  },
  unsubscribeCrosshairMove: (handler: (param: unknown) => void) => {
    crosshairHandlers = crosshairHandlers.filter((h) => h !== handler);
  },
  remove: jest.fn(),
});
export const ColorType = { Solid: 'solid' } as const;
// v5 の addSeries 第一引数（シリーズ種別定義）。実体は使わずダミーで足りる。
export const CandlestickSeries = 'CandlestickSeries';
export const LineSeries = 'LineSeries';
export const HistogramSeries = 'HistogramSeries';
// 🆕 GC/DC・MACDクロスのマーカー表示（`createSeriesMarkers`、v5のトップレベル関数）。
export const createSeriesMarkers = () => ({ setMarkers: jest.fn(), detach: jest.fn() });

// テスト専用ヘルパー: 登録済みの crosshairMove ハンドラを直接呼び出す（本物の
// lightweight-charts API には存在しない）。
export const __emitCrosshairMove = (param: unknown): void => {
  crosshairHandlers.forEach((h) => h(param));
};
