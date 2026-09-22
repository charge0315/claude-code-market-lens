'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { fetchPool, type HorizonType, type PoolCandidate, type PoolSummary } from '@/lib/api/picks';
import './dashboard.css';

// 🆕 P35: 「全銘柄から候補プールへどう絞り込まれたか」の経緯を可視化するパネル。
// `PicksBoard` から「候補プールを見る」ボタンでモーダル表示する。候補プール
// （ショートリスト絞り込み前の全銘柄）を合成スコア降順で一覧し、どの銘柄が
// ショートリスト（LLM深堀り対象）へ進んだかを示す。東証全銘柄→ランキング上位の段階は
// 過去日を再現できるデータが無い（`fetchPool` docstring 参照）ため、件数のみ
// 説明文で示し、一覧には含めない。

const DIRECTION_LABELS: Record<string, string> = { bullish: '強気', bearish: '弱気', neutral: '中立' };

function fmtScore(value: number | null): string {
  return value === null ? '—' : value.toFixed(1);
}

export function PoolPanel({ horizonType, date }: { horizonType: HorizonType; date: string }): ReactNode {
  const [summary, setSummary] = useState<PoolSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPool(horizonType, date)
      .then((s) => {
        setError(null);
        setSummary(s);
      })
      .catch(() => setError('候補プールの取得に失敗しました'));
  }, [horizonType, date]);

  const columns: ReadonlyArray<Column<PoolCandidate>> = [
    {
      key: 'symbol',
      header: '銘柄',
      render: (c) => `${c.symbol}${c.company_name ? `（${c.company_name}）` : ''}`,
    },
    { key: 'composite_score', header: '合成スコア', numeric: true, render: (c) => fmtScore(c.composite_score) },
    { key: 'direction', header: '方向', render: (c) => (c.direction ? (DIRECTION_LABELS[c.direction] ?? c.direction) : '—') },
    { key: 'technical', header: 'テクニカル', numeric: true, render: (c) => fmtScore(c.score_breakdown.technical ?? null) },
    { key: 'ml_prediction', header: 'ML予測', numeric: true, render: (c) => fmtScore(c.score_breakdown.ml_prediction ?? null) },
    { key: 'fundamental', header: 'ファンダ', numeric: true, render: (c) => fmtScore(c.score_breakdown.fundamental ?? null) },
    { key: 'sentiment', header: 'センチメント', numeric: true, render: (c) => fmtScore(c.score_breakdown.sentiment ?? null) },
    { key: 'trend_score', header: 'トレンド', numeric: true, render: (c) => fmtScore(c.trend_score) },
    {
      key: 'status',
      header: '状態',
      render: (c) => (
        <span className={c.is_shortlisted ? 'pool-status-shortlisted' : 'pool-status-pool-only'}>
          {c.is_shortlisted ? 'ショートリスト進出' : '候補プール止まり'}
        </span>
      ),
    },
  ];

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (!summary) return <p className="signal-queue-empty">読み込み中…</p>;

  return (
    <div className="pool-panel">
      <div className="pool-funnel">
        <div className="pool-funnel-stage">
          <span className="pool-funnel-count">{summary.universe_ranking_pool_size}</span>
          <span className="pool-funnel-label">値上がり/値下がり/出来高 各TOP</span>
        </div>
        <span className="pool-funnel-arrow" aria-hidden="true">
          →
        </span>
        <div className="pool-funnel-stage">
          <span className="pool-funnel-count">{summary.total_candidates}</span>
          <span className="pool-funnel-label">候補プール（上限{summary.pool_limit}）</span>
        </div>
        <span className="pool-funnel-arrow" aria-hidden="true">
          →
        </span>
        <div className="pool-funnel-stage">
          <span className="pool-funnel-count">{summary.shortlisted_count}</span>
          <span className="pool-funnel-label">ショートリスト（上限{summary.shortlist_limit}）</span>
        </div>
        <span className="pool-funnel-arrow" aria-hidden="true">
          →
        </span>
        <div className="pool-funnel-stage">
          <span className="pool-funnel-count">最大{summary.max_picks}</span>
          <span className="pool-funnel-label">最終ピック</span>
        </div>
      </div>

      <p className="pool-panel-note">
        値上がり率・値下がり率・出来高の各上位{summary.universe_ranking_pool_size}
        銘柄（東証全銘柄が母集団）から重複除去して候補プールを作り、4分析（テクニカル/トレンド/
        ファンダメンタル/センチメント）の合成スコア降順でショートリストへ絞り込みます。出来高や
        セクター等の個別フィルタは設けていません。
      </p>

      <DataTable
        caption={`${horizonType === 'mid_term' ? '中長期' : '短期'}候補プール一覧（${summary.date}）`}
        columns={columns}
        rows={summary.candidates}
        rowKey={(c) => c.symbol}
        emptyMessage="この日の候補プールデータはまだありません"
      />
    </div>
  );
}
