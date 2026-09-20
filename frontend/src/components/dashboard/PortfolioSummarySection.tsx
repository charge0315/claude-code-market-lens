'use client';

import Link from 'next/link';
import { useEffect, useState, type ReactNode } from 'react';
import { fetchPortfolio, type PortfolioSummary } from '@/lib/api/portfolio';
import './dashboard.css';

// ダッシュボードでの保有ポートフォリオ概況（ユーザー指示: 銘柄概要 + トータル収支）。
// 売却・承認キュー等の操作は既存のポートフォリオ画面に譲り、ここでは一覧性のみ。
// 取得失敗時は MarketTickerBar 同様フェイルソフト（ダッシュボード全体の表示を妨げない）。

const MAX_HOLDINGS_PREVIEW = 6;

function formatYen(value: number | null): string {
  return value === null ? '—' : `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function formatPct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`;
}

function directionColor(value: number | null): string {
  if (value === null || value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

export function PortfolioSummarySection(): ReactNode {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);

  useEffect(() => {
    fetchPortfolio()
      .then(setSummary)
      .catch(() => setSummary(null));
  }, []);

  if (summary === null) return null;

  const previewHoldings = summary.holdings.slice(0, MAX_HOLDINGS_PREVIEW);
  const remaining = summary.holdings.length - previewHoldings.length;

  return (
    <div className="portfolio-summary">
      <div className="portfolio-summary-totals">
        <div className="pick-card-bracket-item">
          <span className="pick-card-bracket-label">評価額合計</span>
          <span className="pick-card-bracket-value">{formatYen(summary.total_value)}</span>
        </div>
        <div className="pick-card-bracket-item">
          <span className="pick-card-bracket-label">評価損益</span>
          <span className="pick-card-bracket-value" style={{ color: directionColor(summary.total_gain_loss) }}>
            {formatYen(summary.total_gain_loss)}
          </span>
        </div>
        <div className="pick-card-bracket-item">
          <span className="pick-card-bracket-label">騰落率</span>
          <span className="pick-card-bracket-value" style={{ color: directionColor(summary.total_return_pct) }}>
            {formatPct(summary.total_return_pct)}
          </span>
        </div>
        <div className="pick-card-bracket-item">
          <span className="pick-card-bracket-label">保有銘柄数</span>
          <span className="pick-card-bracket-value">{summary.holding_count}銘柄</span>
        </div>
      </div>

      {previewHoldings.length === 0 ? (
        <p className="data-table-empty">保有銘柄がありません</p>
      ) : (
        <ul className="portfolio-summary-holdings">
          {previewHoldings.map((h) => (
            <li key={h.holding_id} className="portfolio-summary-holding">
              <span className="portfolio-summary-holding-symbol">
                {h.symbol}
                {h.company_name && ` ${h.company_name}`}
              </span>
              <span className="portfolio-summary-holding-value">{formatYen(h.current_value)}</span>
              <span className="portfolio-summary-holding-pl" style={{ color: directionColor(h.gain_loss) }}>
                {formatYen(h.gain_loss)}（{formatPct(h.return_pct)}）
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="portfolio-summary-footer">
        {remaining > 0 && <span className="portfolio-summary-more">ほか{remaining}銘柄</span>}
        <Link href="/portfolio" className="portfolio-summary-link">
          ポートフォリオで詳細を見る
        </Link>
      </div>
    </div>
  );
}
