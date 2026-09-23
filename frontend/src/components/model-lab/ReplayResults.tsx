import type { ReactNode } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import type {
  CalibrationBucket,
  PerformanceStats,
  ReplayDetail,
  ReplayHorizonType,
  ReplaySummary,
} from '@/lib/api/replay';

// 過去日リプレイ（🆕 P37）の成績・学習結果の表示（表示専用、状態を持たない）。
// 騰落色は国内証券標準（プラス = 赤 `.gain` / マイナス = 緑 `.loss`）。

const HORIZON_LABELS: Record<ReplayHorizonType, string> = {
  short_term: '短期',
  mid_term: '中長期',
};
const HORIZON_ORDER: ReadonlyArray<ReplayHorizonType> = ['short_term', 'mid_term'];
const FACTOR_LABELS: Record<string, string> = {
  composite: '合成スコア',
  technical: 'テクニカル',
  ml_prediction: 'ML予測',
  fundamental: 'ファンダメンタル',
  sentiment: 'センチメント',
  trend: 'トレンド',
};

export function formatPct(value: number | undefined, digits = 1): string {
  return value === undefined ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function SignedPct({ value }: { value: number | undefined }): ReactNode {
  if (value === undefined) return '—';
  const cls = value > 0 ? 'gain' : value < 0 ? 'loss' : 'flat';
  const sign = value > 0 ? '+' : '';
  return <span className={cls}>{`${sign}${(value * 100).toFixed(2)}%`}</span>;
}

interface PerfRow {
  horizon: ReplayHorizonType;
  horizonDays: number;
  perf: PerformanceStats;
}

const PERF_COLUMNS: ReadonlyArray<Column<PerfRow>> = [
  { key: 'horizon', header: '系統', render: (r) => HORIZON_LABELS[r.horizon] },
  {
    key: 'horizonDays',
    header: '評価日数',
    numeric: true,
    render: (r) => `${r.horizonDays}営業日`,
  },
  {
    key: 'n',
    header: '決着件数',
    numeric: true,
    render: (r) => r.perf.n.toLocaleString('ja-JP'),
  },
  {
    key: 'win',
    header: '勝率',
    numeric: true,
    render: (r) => formatPct(r.perf.win_rate),
  },
  {
    key: 'excess',
    header: '平均超過リターン',
    numeric: true,
    render: (r) => <SignedPct value={r.perf.avg_excess} />,
  },
  {
    key: 'target',
    header: '利確到達率',
    numeric: true,
    render: (r) => formatPct(r.perf.hit_target_rate),
  },
];

export function LivePerformanceTable({ detail }: { detail: ReplayDetail }): ReactNode {
  const rows: PerfRow[] = HORIZON_ORDER.map((h) => ({
    horizon: h,
    horizonDays: detail.live[h].horizon_days,
    perf: detail.live[h].performance,
  }));
  return (
    <DataTable
      caption="リプレイの答え合わせ成績（決着済みの分のみ）"
      columns={PERF_COLUMNS}
      rows={rows}
      rowKey={(r) => r.horizon}
    />
  );
}

interface CalibRow extends CalibrationBucket {
  horizon: ReplayHorizonType;
}

const CALIB_COLUMNS: ReadonlyArray<Column<CalibRow>> = [
  { key: 'horizon', header: '系統', render: (r) => HORIZON_LABELS[r.horizon] },
  {
    key: 'bucket',
    header: '合成スコア帯',
    numeric: true,
    render: (r) => `${r.bucket_low}〜${r.bucket_high}`,
  },
  {
    key: 'n',
    header: '件数',
    numeric: true,
    render: (r) => r.n.toLocaleString('ja-JP'),
  },
  {
    key: 'win_rate',
    header: '実測勝率',
    numeric: true,
    render: (r) => formatPct(r.win_rate),
  },
];

interface IcRow {
  factor: string;
  ics: Partial<Record<ReplayHorizonType, number | null>>;
  weights: Partial<Record<ReplayHorizonType, number>>;
}

function formatIc(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toFixed(3);
}

const IC_COLUMNS: ReadonlyArray<Column<IcRow>> = [
  {
    key: 'factor',
    header: 'ファクター',
    render: (r) => FACTOR_LABELS[r.factor] ?? r.factor,
  },
  {
    key: 'ic_short',
    header: 'IC（短期）',
    numeric: true,
    render: (r) => formatIc(r.ics.short_term),
  },
  {
    key: 'ic_mid',
    header: 'IC（中長期）',
    numeric: true,
    render: (r) => formatIc(r.ics.mid_term),
  },
  {
    key: 'w_short',
    header: '実測重み（短期）',
    numeric: true,
    render: (r) => (r.weights.short_term === undefined ? '—' : formatPct(r.weights.short_term, 0)),
  },
  {
    key: 'w_mid',
    header: '実測重み（中長期）',
    numeric: true,
    render: (r) => (r.weights.mid_term === undefined ? '—' : formatPct(r.weights.mid_term, 0)),
  },
];

function gateBlock(summary: ReplaySummary, horizon: ReplayHorizonType) {
  const days = summary.calibration[horizon]?.horizon_days;
  return days === undefined ? undefined : summary.horizons[horizon]?.[String(days)];
}

export function SummaryTables({ summary }: { summary: ReplaySummary }): ReactNode {
  const calibRows: CalibRow[] = HORIZON_ORDER.flatMap((h) =>
    (gateBlock(summary, h)?.calibration_table ?? []).map((b) => ({
      ...b,
      horizon: h,
    })),
  );
  const factors = Object.keys(FACTOR_LABELS);
  const icRows: IcRow[] = factors.map((factor) => ({
    factor,
    ics: {
      short_term: gateBlock(summary, 'short_term')?.factor_ics[factor],
      mid_term: gateBlock(summary, 'mid_term')?.factor_ics[factor],
    },
    weights: {
      short_term: summary.ic_weights.short_term?.[factor],
      mid_term: summary.ic_weights.mid_term?.[factor],
    },
  }));

  return (
    <div className="replay-summary">
      <h3 className="replay-subheading">合成スコア帯ごとの実測勝率</h3>
      <p className="model-lab-as-of">
        スコアが高い帯ほど勝率も高ければ、合成スコアの順位付けが機能しています（短期 3 / 中長期 20 営業日で評価）。
      </p>
      <DataTable
        caption="合成スコア帯ごとの実測勝率"
        columns={CALIB_COLUMNS}
        rows={calibRows}
        rowKey={(r) => `${r.horizon}-${r.bucket_low}`}
        emptyMessage="決着済みのピックがまだありません"
      />

      <h3 className="replay-subheading">ファクター別の予測力（IC）と実測重み</h3>
      <p className="model-lab-as-of">
        IC はスコアと超過リターンの順位相関です。実測重みは参考表示で、本番の合成スコアには自動反映しません。
        過去時点の値が残っていないファンダメンタル・センチメントは「—」になります。
      </p>
      <DataTable caption="ファクター別 IC と実測重み" columns={IC_COLUMNS} rows={icRows} rowKey={(r) => r.factor} />

      <p className="model-lab-as-of replay-challenger">
        {summary.challenger_version
          ? `最後に学び直した断面プールモデルを challenger「${summary.challenger_version}」として登録しました。本番への採用は「モデルバージョン比較」の昇格判定と人手承認を経てのみ行われます。`
          : 'challenger として登録できるモデルはありませんでした（学習データ不足）。'}
      </p>
    </div>
  );
}
