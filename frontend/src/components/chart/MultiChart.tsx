'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { CandlestickSeries, createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { fetchOhlc, type OhlcInterval, type OhlcPeriod } from '@/lib/api/stock';
import { toChartTime } from '@/lib/chartTime';
import { analyzeBars, type TimeframeInsight, type TimeframeSet } from '@/lib/multiChartInsights';
import { MultiChartInsightSummary, TimeframeInsightList } from '@/components/chart/MultiChartInsights';
import './chart.css';

// 🆕 マルチチャート: 複数の足種を同時に並べて一覧できるグリッド（四季報オンラインの
// 「マルチチャート」タブを参考にした、`/chart` 画面限定の機能）。対応範囲は既存3足種
// （日足/60分足/15分足）のみに絞る（週足/月足/年足は backend の `_Interval` が未対応で、
// 追加するとyfinanceの新規interval取得実装が要りスコープが大きく広がるため対象外、
// ユーザー確認済み）。各パネルは一覧性重視の縮小表示で、期間切替やオーバーレイ指標などの
// 操作は行わない（詳細に見たい場合は「通常チャート」タブ側で行う）。

interface PanelConfig {
  interval: OhlcInterval;
  period: OhlcPeriod;
  label: string;
}

const PANELS: ReadonlyArray<PanelConfig> = [
  { interval: '15m', period: '1mo', label: '15分足（1ヶ月）' },
  { interval: '60m', period: '3mo', label: '60分足（3ヶ月）' },
  { interval: '1d', period: '1y', label: '日足（1年）' },
];

const MINI_CHART_HEIGHT = 200;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// 足種 → 所見サマリーでの役割（短期/中期/長期）の対応。
const TIMEFRAME_ROLE: Record<OhlcInterval, keyof TimeframeSet> = { '15m': 'short', '60m': 'mid', '1d': 'long' };

interface MiniChartPanelProps {
  symbol: string;
  config: PanelConfig;
  insight: TimeframeInsight | null;
  // 🆕 所見（チャートから読み取れること）を横断集計するため、取得した足データの解析結果を
  // 親へ渡す。取得失敗時は null を渡して古い銘柄の所見が残らないようにする。
  onInsight: (symbol: string, interval: OhlcInterval, insight: TimeframeInsight | null) => void;
}

interface InsightState {
  symbol: string;
  byInterval: Partial<Record<OhlcInterval, TimeframeInsight>>;
}

function MiniChartPanel({ symbol, config, insight, onInsight }: MiniChartPanelProps): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const [error, setError] = useState(false);
  const [isEmpty, setIsEmpty] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: { background: { color: 'transparent' }, textColor: cssVar('--color-text-secondary') },
      grid: {
        vertLines: { color: cssVar('--color-border') },
        horzLines: { color: cssVar('--color-border') },
      },
      width: container.clientWidth,
      height: MINI_CHART_HEIGHT,
      timeScale: { borderColor: cssVar('--color-border') },
      rightPriceScale: { borderColor: cssVar('--color-border') },
      handleScroll: false,
      handleScale: false,
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
    chartRef.current = chart;

    const handleResize = (): void => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    fetchOhlc(symbol, config.period, config.interval)
      .then(({ bars }) => {
        setError(false);
        setIsEmpty(bars.length === 0);
        seriesRef.current?.setData(
          bars.map((b) => ({ time: toChartTime(b.time), open: b.open, high: b.high, low: b.low, close: b.close }))
        );
        chartRef.current?.timeScale().fitContent();
        onInsight(symbol, config.interval, analyzeBars(bars));
      })
      .catch(() => {
        setError(true);
        onInsight(symbol, config.interval, null);
      });
  }, [symbol, config.period, config.interval, onInsight]);

  return (
    <div className="multi-chart-panel">
      <h3 className="multi-chart-panel-title">{config.label}</h3>
      {error && <p className="signal-queue-error">取得に失敗しました</p>}
      {isEmpty && !error && <p className="signal-queue-empty">データがありません</p>}
      <div ref={containerRef} className="multi-chart-panel-canvas" role="img" aria-label={`${symbol} の${config.label}`} />
      {insight && <TimeframeInsightList insight={insight} />}
    </div>
  );
}

export function MultiChart({ symbol }: { symbol: string }): ReactNode {
  // 所見はどの銘柄の取得結果かを併せて持ち、表示中の銘柄と一致するものだけを使う
  // （銘柄切替直後に前の銘柄の説明が残らないようにするため）。
  const [stored, setStored] = useState<InsightState>({ symbol, byInterval: {} });
  const insights = stored.symbol === symbol ? stored.byInterval : {};

  const handleInsight = useCallback(
    (fetchedSymbol: string, interval: OhlcInterval, insight: TimeframeInsight | null): void => {
      setStored((prev) => {
        const base = prev.symbol === fetchedSymbol ? prev.byInterval : {};
        return { symbol: fetchedSymbol, byInterval: { ...base, [interval]: insight ?? undefined } };
      });
    },
    []
  );

  const timeframes: TimeframeSet = PANELS.reduce<TimeframeSet>((acc, { interval }) => {
    const insight = insights[interval];
    return insight ? { ...acc, [TIMEFRAME_ROLE[interval]]: insight } : acc;
  }, {});

  return (
    <div className="multi-chart">
      <div className="multi-chart-grid">
        {PANELS.map((config) => (
          <MiniChartPanel
            key={config.interval}
            symbol={symbol}
            config={config}
            insight={insights[config.interval] ?? null}
            onInsight={handleInsight}
          />
        ))}
      </div>
      <MultiChartInsightSummary timeframes={timeframes} />
    </div>
  );
}
