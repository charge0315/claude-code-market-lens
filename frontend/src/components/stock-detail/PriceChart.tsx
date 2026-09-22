'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type IPaneApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import {
  fetchOhlc,
  type ChartEvent,
  type OhlcInterval,
  type OhlcPeriod,
  type OverlayKind,
  type SubIndicatorKind,
} from '@/lib/api/stock';
import { toChartTime } from '@/lib/chartTime';
import './stock-detail.css';

// 日足ローソク足チャート（既定）。🆕 `enableAdvancedControls` を渡すと足種セレクタ（分足）・
// オーバーレイ指標・サブインジケーターも選べるようになる — 対象は `/chart` 画面のみ
// （任意銘柄を素早く見る用途では、四季報オンライン等のプロ向けチャートと同等の粒度・
// 指標が欲しいというユーザー要望）。銘柄詳細画面はチャートが補助情報という位置づけ
// （CLAUDE.md の主要画面定義）のため、そちらは従来どおり日足・マーカーのみで据え置く。
//
// 🆕 ゴールデンクロス/デッドクロス・MACDクロスの兆候イベントをマーカーで示し、hoverすると
// 簡単な説明をツールチップで表示する。マーカー色は国内証券標準の騰落色トークン
// （--color-gain=赤/--color-loss=緑）を流用し、買い兆候=赤・警戒/売り兆候=緑で統一する。
// オーバーレイ・サブインジケーター・分足では兆候イベント自体を検出しない
// （`routers/stock.py` 参照、日付キーが同日内で衝突するため）。

const PERIODS: ReadonlyArray<OhlcPeriod> = ['1mo', '3mo', '6mo', '1y', '2y'];
const PERIOD_LABELS: Record<OhlcPeriod, string> = { '1mo': '1ヶ月', '3mo': '3ヶ月', '6mo': '6ヶ月', '1y': '1年', '2y': '2年' };

const INTERVALS: ReadonlyArray<OhlcInterval> = ['1d', '60m', '15m'];
const INTERVAL_LABELS: Record<OhlcInterval, string> = { '1d': '日足', '60m': '60分足', '15m': '15分足' };
// 足種ごとに選べる期間（バックエンド `_INTRADAY_ALLOWED_PERIODS` と同期させること）。
// 分足は Yahoo Finance の取得可能期間の上限（60分足=730日・15分足=60日）に収まる範囲に絞る。
const INTERVAL_PERIODS: Record<OhlcInterval, ReadonlyArray<OhlcPeriod>> = {
  '1d': PERIODS,
  '60m': ['1mo', '3mo', '6mo', '1y'],
  '15m': ['1mo'],
};
const CHART_HEIGHT = 300;
// 🆕 サブインジケーターペインの高さ比率（メインペインを 1 としたときの相対値）。
const SUB_PANE_STRETCH_FACTOR = 0.35;

// 🆕 価格チャートに重ねるオーバーレイ指標。日足専用（分足は backend が overlay=null を返す）。
const OVERLAYS: ReadonlyArray<OverlayKind> = ['sma', 'ichimoku', 'bollinger'];
const OVERLAY_LABELS: Record<OverlayKind, string> = {
  sma: '移動平均線',
  ichimoku: '一目均衡表',
  bollinger: 'ボリンジャーバンド',
};

// 🆕 下段ペインのサブインジケーター。'volume'（出来高）のみ `bars` から直接描画するため
// バックエンドへは問い合わせない（他の3種は日足専用で `sub_indicator` API 経由）。
type SubPaneKind = 'volume' | SubIndicatorKind;
const SUB_PANES: ReadonlyArray<SubPaneKind> = ['volume', 'macd', 'rsi', 'stochastics'];
const SUB_PANE_LABELS: Record<SubPaneKind, string> = {
  volume: '出来高',
  macd: 'MACD',
  rsi: 'RSI',
  stochastics: 'ストキャスティクス',
};

// 複数系列を描き分けるための配色（ブランドの2アクセント色の濃淡を巡回利用する。
// 新規の任意色を持ち込まず、既存デザイントークンの範囲で指標線を塗り分けるため）。
const LINE_PALETTE = [
  '--color-accent-500',
  '--color-accent-2-500',
  '--color-accent-700',
  '--color-accent-2-700',
  '--color-accent-300',
] as const;

// 🆕 ツールチップ見出し。`label`（バックエンド生成の説明文）とは別に、種別を一目で識別
// できるよう短い名称を添える（同系色で埋もれるマーカー視認性の改善に合わせた強調表示）。
const EVENT_TITLES: Record<ChartEvent['kind'], string> = {
  golden_cross: 'ゴールデンクロス',
  dead_cross: 'デッドクロス',
  macd_bullish_cross: 'MACDゴールデンクロス',
  macd_bearish_cross: 'MACDデッドクロス',
};

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function isBearishEvent(kind: ChartEvent['kind']): boolean {
  return kind === 'dead_cross' || kind === 'macd_bearish_cross';
}

// lightweight-charts の crosshair イベントが返す `Time`（string | number | BusinessDay）を
// `events` の date（YYYY-MM-DD）と突き合わせられる文字列キーへ変換する。
function timeToDateKey(time: Time): string {
  if (typeof time === 'object') {
    return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`;
  }
  return String(time);
}

interface PriceChartProps {
  symbol: string;
  // 🆕 true のとき足種（日足/60分足/15分足）・オーバーレイ指標・サブインジケーターの
  // セレクタを表示する（`/chart` 画面専用）。
  enableAdvancedControls?: boolean;
}

export function PriceChart({ symbol, enableAdvancedControls = false }: PriceChartProps): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const subPaneRef = useRef<IPaneApi<Time> | null>(null);
  // オーバーレイ/サブインジケーターは選択が変わるたびに古い系列を消してから新しい系列を
  // 追加する必要があるため、現在追加済みの系列を配列で保持しておく。
  const overlaySeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const subPaneSeriesRef = useRef<ISeriesApi<'Line' | 'Histogram'>[]>([]);
  const eventsByDateRef = useRef<Map<string, ChartEvent>>(new Map());
  const [ohlcInterval, setOhlcInterval] = useState<OhlcInterval>('1d');
  const [period, setPeriod] = useState<OhlcPeriod>('6mo');
  const [overlay, setOverlay] = useState<OverlayKind>('sma');
  const [subPane, setSubPane] = useState<SubPaneKind>('volume');
  const [error, setError] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(false);
  const [hoverEvent, setHoverEvent] = useState<ChartEvent | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);

  const availablePeriods = enableAdvancedControls ? INTERVAL_PERIODS[ohlcInterval] : PERIODS;

  // 足種を切り替えたとき、現在の期間がその足種で選べない場合（例: 60分足→15分足）は
  // その足種で選べる最初の期間へ自動的に丸める。
  function handleIntervalChange(next: OhlcInterval): void {
    setOhlcInterval(next);
    if (!INTERVAL_PERIODS[next].includes(period)) {
      setPeriod(INTERVAL_PERIODS[next][0]);
    }
  }

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart: IChartApi = createChart(container, {
      layout: { background: { color: 'transparent' }, textColor: cssVar('--color-text-secondary') },
      grid: {
        vertLines: { color: cssVar('--color-border') },
        horzLines: { color: cssVar('--color-border') },
      },
      width: container.clientWidth,
      height: CHART_HEIGHT,
      timeScale: { borderColor: cssVar('--color-border') },
      rightPriceScale: { borderColor: cssVar('--color-border') },
    });
    const gain = cssVar('--color-gain');
    const loss = cssVar('--color-loss');
    const series = chart.addSeries(CandlestickSeries, {
      upColor: gain,
      downColor: loss,
      borderUpColor: gain,
      borderDownColor: loss,
      wickUpColor: gain,
      wickDownColor: loss,
    });
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series);
    chartRef.current = chart;

    // 🆕 サブインジケーター（出来高/MACD/RSI/ストキャスティクス）用の下段ペイン。
    // メインの価格ペイン（index 0）とは別に作り、常時表示ではなく選択された指標の
    // 系列だけをその都度追加/削除する（`enableAdvancedControls` が false でも作成は
    // しておき、単に系列を追加しないことで実質非表示にする — ペインの有無を条件分岐
    // すると再マウントが必要になり複雑になるため）。
    // `preserveEmptyPane: true` — サブインジケーター切り替え時に一旦全系列を削除してから
    // 追加し直す実装のため、瞬間的に系列ゼロになるタイミングでペイン自体が自動削除されない
    // ようにする（既定 false だとペイン消滅→直後の addSeries が内部アサーションで例外を投げる）。
    const subPane = chart.addPane(true);
    subPane.setStretchFactor(SUB_PANE_STRETCH_FACTOR);
    subPaneRef.current = subPane;

    const handleCrosshairMove = (param: MouseEventParams<Time>): void => {
      const event = param.time ? eventsByDateRef.current.get(timeToDateKey(param.time)) : undefined;
      setHoverEvent(event ?? null);
      setHoverPos(event && param.point ? { x: param.point.x, y: param.point.y } : null);
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    const handleResize = (): void => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      markersRef.current?.detach();
      markersRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      subPaneRef.current = null;
      overlaySeriesRef.current = [];
      subPaneSeriesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const requestOverlay = enableAdvancedControls ? overlay : undefined;
    const requestSubIndicator = enableAdvancedControls && subPane !== 'volume' ? subPane : undefined;

    fetchOhlc(symbol, period, ohlcInterval, requestOverlay, requestSubIndicator)
      .then(({ bars, events, overlay: overlayData, sub_indicator: subIndicatorData }) => {
        setIsEmpty(bars.length === 0);
        setHoverEvent(null);
        setHoverPos(null);
        seriesRef.current?.setData(
          bars.map((b) => ({ time: toChartTime(b.time), open: b.open, high: b.high, low: b.low, close: b.close }))
        );

        // 前回選択分のオーバーレイ系列を消してから、今回のデータで作り直す。
        overlaySeriesRef.current.forEach((s) => chartRef.current?.removeSeries(s));
        overlaySeriesRef.current = (overlayData ? Object.entries(overlayData.lines) : []).map(
          ([name, points], i) => {
            const lineSeries = chartRef.current!.addSeries(LineSeries, {
              color: cssVar(LINE_PALETTE[i % LINE_PALETTE.length]),
              lineWidth: 1,
              title: name,
              lastValueVisible: false,
              priceLineVisible: false,
            });
            lineSeries.setData(
              points.filter((p) => p.value !== null).map((p) => ({ time: toChartTime(p.time), value: p.value! }))
            );
            return lineSeries;
          }
        );

        // 同様にサブインジケーターペインの系列も作り直す。
        subPaneSeriesRef.current.forEach((s) => chartRef.current?.removeSeries(s));
        if (subPane === 'volume') {
          const gain = cssVar('--color-gain');
          const loss = cssVar('--color-loss');
          const volumeSeries = subPaneRef.current!.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            lastValueVisible: false,
            priceLineVisible: false,
          });
          volumeSeries.setData(
            bars.map((b) => ({ time: toChartTime(b.time), value: b.volume, color: b.close >= b.open ? gain : loss }))
          );
          subPaneSeriesRef.current = [volumeSeries];
        } else if (subIndicatorData) {
          subPaneSeriesRef.current = Object.entries(subIndicatorData.lines).map(([name, points], i) => {
            const lineSeries = subPaneRef.current!.addSeries(LineSeries, {
              color: cssVar(LINE_PALETTE[i % LINE_PALETTE.length]),
              lineWidth: 1,
              title: name,
              lastValueVisible: false,
              priceLineVisible: false,
            });
            lineSeries.setData(
              points.filter((p) => p.value !== null).map((p) => ({ time: toChartTime(p.time), value: p.value! }))
            );
            return lineSeries;
          });
        } else {
          subPaneSeriesRef.current = [];
        }

        // データの開始点（最も古い足）が左端から見えるよう、期間全体を表示領域に収める。
        chartRef.current?.timeScale().fitContent();

        eventsByDateRef.current = new Map(events.map((e) => [e.date, e]));
        // ローソク足自体が --color-gain/--color-loss（赤/緑）を使うため、同じ色をマーカーに
        // 流用すると同系色で埋もれて見えづらい（ユーザー指摘）。マーカーはブランドアクセント色
        // （オレンジ=強気 / オリーブ=弱気）で塗り分け、価格の騰落色とは独立させて視認性を確保する。
        const bullishMarker = cssVar('--color-accent-bright');
        const bearishMarker = cssVar('--color-accent-2-bright');
        const markers: SeriesMarker<Time>[] = events.map((e) => {
          const bearish = isBearishEvent(e.kind);
          return {
            time: e.date,
            position: bearish ? 'aboveBar' : 'belowBar',
            color: bearish ? bearishMarker : bullishMarker,
            shape: bearish ? 'arrowDown' : 'arrowUp',
            size: 2,
            id: `${e.kind}-${e.date}`,
          };
        });
        markersRef.current?.setMarkers(markers);
      })
      .catch(() => setError('株価データの取得に失敗しました'));
  }, [symbol, period, ohlcInterval, overlay, subPane, enableAdvancedControls]);

  return (
    <div className="price-chart">
      {enableAdvancedControls && (
        <div className="price-chart-toolbar" role="group" aria-label="足種">
          {INTERVALS.map((i) => (
            <button
              key={i}
              type="button"
              className={ohlcInterval === i ? 'is-active' : undefined}
              aria-pressed={ohlcInterval === i}
              onClick={() => handleIntervalChange(i)}
            >
              {INTERVAL_LABELS[i]}
            </button>
          ))}
        </div>
      )}

      <div className="price-chart-toolbar" role="group" aria-label="表示期間">
        {availablePeriods.map((p) => (
          <button
            key={p}
            type="button"
            className={period === p ? 'is-active' : undefined}
            aria-pressed={period === p}
            onClick={() => setPeriod(p)}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {enableAdvancedControls && (
        <>
          <div className="price-chart-toolbar" role="group" aria-label="オーバーレイ指標">
            {OVERLAYS.map((o) => (
              <button
                key={o}
                type="button"
                className={overlay === o ? 'is-active' : undefined}
                aria-pressed={overlay === o}
                onClick={() => setOverlay(o)}
              >
                {OVERLAY_LABELS[o]}
              </button>
            ))}
          </div>

          <div className="price-chart-toolbar" role="group" aria-label="サブインジケーター">
            {SUB_PANES.map((s) => (
              <button
                key={s}
                type="button"
                className={subPane === s ? 'is-active' : undefined}
                aria-pressed={subPane === s}
                onClick={() => setSubPane(s)}
              >
                {SUB_PANE_LABELS[s]}
              </button>
            ))}
          </div>
        </>
      )}

      {error && <p className="signal-queue-error">{error}</p>}
      {isEmpty && !error && <p className="signal-queue-empty">株価データがありません</p>}

      <div className="price-chart-canvas-wrap">
        <div
          ref={containerRef}
          className="price-chart-canvas"
          role="img"
          aria-label={`${symbol} の${INTERVAL_LABELS[ohlcInterval]}ローソク足チャート`}
        />
        {hoverEvent && hoverPos && (
          <div
            className="price-chart-tooltip"
            data-signal={isBearishEvent(hoverEvent.kind) ? 'bearish' : 'bullish'}
            style={{ left: hoverPos.x, top: hoverPos.y }}
            role="tooltip"
          >
            <strong className="price-chart-tooltip-title">{EVENT_TITLES[hoverEvent.kind]}</strong>
            <p className="price-chart-tooltip-body">{hoverEvent.label}</p>
          </div>
        )}
      </div>
    </div>
  );
}
