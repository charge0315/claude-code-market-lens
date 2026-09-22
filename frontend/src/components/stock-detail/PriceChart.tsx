'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import { fetchOhlc, type ChartEvent, type OhlcInterval, type OhlcPeriod } from '@/lib/api/stock';
import './stock-detail.css';

// 日足ローソク足チャート（既定）。🆕 `enableIntervalSelector` を渡すと分足（60分足/15分足）も
// 選べる足種セレクタを表示する — 対象は `/chart` 画面のみ（任意銘柄を素早く見る用途では
// より細かい粒度が欲しいというユーザー要望）。銘柄詳細画面はチャートが補助情報という
// 位置づけ（CLAUDE.md の主要画面定義）のため、そちらは従来どおり日足のみで据え置く。
//
// 🆕 ゴールデンクロス/デッドクロス・MACDクロスの兆候イベントをマーカーで示し、hoverすると
// 簡単な説明をツールチップで表示する。マーカー色は国内証券標準の騰落色トークン
// （--color-gain=赤/--color-loss=緑）を流用し、買い兆候=赤・警戒/売り兆候=緑で統一する。
// 分足では兆候イベント自体を検出しない（`routers/stock.py` 参照、日付キーが同日内で
// 衝突するため）。

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

// lightweight-charts の `Time` は分足（Unix秒）と日足（YYYY-MM-DD文字列）を区別できないため、
// 数値は `UTCTimestamp` へ明示キャストする（公式ドキュメント推奨の書き方）。
function toChartTime(time: string | number): Time {
  return typeof time === 'number' ? (time as UTCTimestamp) : time;
}

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
  // 🆕 true のとき足種（日足/60分足/15分足）セレクタを表示する（`/chart` 画面専用）。
  enableIntervalSelector?: boolean;
}

export function PriceChart({ symbol, enableIntervalSelector = false }: PriceChartProps): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const eventsByDateRef = useRef<Map<string, ChartEvent>>(new Map());
  const [ohlcInterval, setOhlcInterval] = useState<OhlcInterval>('1d');
  const [period, setPeriod] = useState<OhlcPeriod>('6mo');
  const [error, setError] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(false);
  const [hoverEvent, setHoverEvent] = useState<ChartEvent | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);

  const availablePeriods = enableIntervalSelector ? INTERVAL_PERIODS[ohlcInterval] : PERIODS;

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
    };
  }, []);

  useEffect(() => {
    fetchOhlc(symbol, period, ohlcInterval)
      .then(({ bars, events }) => {
        setIsEmpty(bars.length === 0);
        setHoverEvent(null);
        setHoverPos(null);
        seriesRef.current?.setData(
          bars.map((b) => ({ time: toChartTime(b.time), open: b.open, high: b.high, low: b.low, close: b.close }))
        );
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
  }, [symbol, period, ohlcInterval]);

  return (
    <div className="price-chart">
      {enableIntervalSelector && (
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
