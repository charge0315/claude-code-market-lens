'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CandlestickSeries, createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { fetchOhlc, type OhlcInterval, type OhlcPeriod } from '@/lib/api/stock';
import { toChartTime } from '@/lib/chartTime';
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

function MiniChartPanel({ symbol, config }: { symbol: string; config: PanelConfig }): ReactNode {
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
      })
      .catch(() => setError(true));
  }, [symbol, config.period, config.interval]);

  return (
    <div className="multi-chart-panel">
      <h3 className="multi-chart-panel-title">{config.label}</h3>
      {error && <p className="signal-queue-error">取得に失敗しました</p>}
      {isEmpty && !error && <p className="signal-queue-empty">データがありません</p>}
      <div ref={containerRef} className="multi-chart-panel-canvas" role="img" aria-label={`${symbol} の${config.label}`} />
    </div>
  );
}

export function MultiChart({ symbol }: { symbol: string }): ReactNode {
  return (
    <div className="multi-chart-grid">
      {PANELS.map((config) => (
        <MiniChartPanel key={config.interval} symbol={symbol} config={config} />
      ))}
    </div>
  );
}
