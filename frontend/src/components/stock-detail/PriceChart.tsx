'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CandlestickSeries, createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { fetchOhlc, type OhlcPeriod } from '@/lib/api/stock';
import './stock-detail.css';

// 日足ローソク足チャート。複数時間軸（分足等）は対象外 — 銘柄詳細の主目的は AI 思考トレースで
// あり（CLAUDE.md の主要画面定義）、チャートは期間切り替えのみの補助情報という位置づけ。

const PERIODS: ReadonlyArray<OhlcPeriod> = ['1mo', '3mo', '6mo', '1y', '2y'];
const PERIOD_LABELS: Record<OhlcPeriod, string> = { '1mo': '1ヶ月', '3mo': '3ヶ月', '6mo': '6ヶ月', '1y': '1年', '2y': '2年' };
const CHART_HEIGHT = 300;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PriceChart({ symbol }: { symbol: string }): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const [period, setPeriod] = useState<OhlcPeriod>('6mo');
  const [error, setError] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(false);

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
    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: gain,
      downColor: loss,
      borderUpColor: gain,
      borderDownColor: loss,
      wickUpColor: gain,
      wickDownColor: loss,
    });

    const handleResize = (): void => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    fetchOhlc(symbol, period)
      .then((bars) => {
        setIsEmpty(bars.length === 0);
        seriesRef.current?.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
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

      <div ref={containerRef} className="price-chart-canvas" role="img" aria-label={`${symbol} の日足ローソク足チャート`} />
    </div>
  );
}
