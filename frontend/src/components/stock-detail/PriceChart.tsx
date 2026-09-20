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
} from 'lightweight-charts';
import { fetchOhlc, type ChartEvent, type OhlcPeriod } from '@/lib/api/stock';
import './stock-detail.css';

// 日足ローソク足チャート。複数時間軸（分足等）は対象外 — 銘柄詳細の主目的は AI 思考トレースで
// あり（CLAUDE.md の主要画面定義）、チャートは期間切り替えのみの補助情報という位置づけ。
//
// 🆕 ゴールデンクロス/デッドクロス・MACDクロスの兆候イベントをマーカーで示し、hoverすると
// 簡単な説明をツールチップで表示する。マーカー色は国内証券標準の騰落色トークン
// （--color-gain=赤/--color-loss=緑）を流用し、買い兆候=赤・警戒/売り兆候=緑で統一する。

const PERIODS: ReadonlyArray<OhlcPeriod> = ['1mo', '3mo', '6mo', '1y', '2y'];
const PERIOD_LABELS: Record<OhlcPeriod, string> = { '1mo': '1ヶ月', '3mo': '3ヶ月', '6mo': '6ヶ月', '1y': '1年', '2y': '2年' };
const CHART_HEIGHT = 300;

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

export function PriceChart({ symbol }: { symbol: string }): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const eventsByDateRef = useRef<Map<string, ChartEvent>>(new Map());
  const [period, setPeriod] = useState<OhlcPeriod>('6mo');
  const [error, setError] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(false);
  const [hoverEvent, setHoverEvent] = useState<ChartEvent | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);

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
    fetchOhlc(symbol, period)
      .then(({ bars, events }) => {
        setIsEmpty(bars.length === 0);
        setHoverEvent(null);
        setHoverPos(null);
        seriesRef.current?.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
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
  }, [symbol, period]);

  return (
    <div className="price-chart">
      <div className="price-chart-toolbar" role="group" aria-label="表示期間">
        {PERIODS.map((p) => (
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
        <div ref={containerRef} className="price-chart-canvas" role="img" aria-label={`${symbol} の日足ローソク足チャート`} />
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
