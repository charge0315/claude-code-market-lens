import type { OhlcBar } from '@/lib/api/stock';

// マルチチャートの「チャートから読み取れること」を、各足種の OHLC から機械的に算出する。
// LLM を介さずルールベースにしているのは、(1) 同じチャートなら常に同じ説明になる再現性、
// (2) 閲覧のたびに課金が発生しない、(3) 見た目の値動きをそのまま言語化する用途には
// 移動平均・レンジ位置の単純な判定で十分、の3点から。売買推奨ではなく値動きの要約に留める。

export type TrendKind = 'up' | 'down' | 'range';
export type RangePosition = 'high' | 'middle' | 'low';

export interface TimeframeInsight {
  // 表示期間の始値基準ではなく最初の終値→最後の終値の騰落率（%）。
  changePct: number;
  trend: TrendKind;
  rangePosition: RangePosition;
  // 表示期間の安値〜高値レンジ内での直近終値の位置（0=安値、100=高値）。
  rangePct: number;
}

// トレンド判定に使う移動平均の本数と、平均線の傾きを見る比較本数。
// 足種を問わず同じ本数で判定することで「その足種で見たときの流れ」を揃った物差しで比べる。
const MA_WINDOW = 20;
const SLOPE_LOOKBACK = 5;
const MIN_BARS = MA_WINDOW + SLOPE_LOOKBACK;
// レンジ上位/下位 20% を高値圏/安値圏とみなす。
const HIGH_ZONE_PCT = 80;
const LOW_ZONE_PCT = 20;

function movingAverageAt(closes: ReadonlyArray<number>, endIndex: number): number {
  const window = closes.slice(endIndex - MA_WINDOW + 1, endIndex + 1);
  return window.reduce((sum, v) => sum + v, 0) / window.length;
}

function classifyTrend(closes: ReadonlyArray<number>): TrendKind {
  const last = closes.length - 1;
  const maNow = movingAverageAt(closes, last);
  const maBefore = movingAverageAt(closes, last - SLOPE_LOOKBACK);
  const close = closes[last];
  // 「終値が平均線の上」かつ「平均線が上向き」の両方を満たすときだけ上昇基調とする
  // （片方だけなら転換途中の可能性があるため、方向感なしに寄せる）。
  if (close > maNow && maNow > maBefore) return 'up';
  if (close < maNow && maNow < maBefore) return 'down';
  return 'range';
}

function classifyRange(pct: number): RangePosition {
  if (pct >= HIGH_ZONE_PCT) return 'high';
  if (pct <= LOW_ZONE_PCT) return 'low';
  return 'middle';
}

export function analyzeBars(bars: ReadonlyArray<OhlcBar>): TimeframeInsight | null {
  if (bars.length < MIN_BARS) return null;
  const closes = bars.map((b) => b.close);
  const first = closes[0];
  const last = closes[closes.length - 1];
  const high = Math.max(...bars.map((b) => b.high));
  const low = Math.min(...bars.map((b) => b.low));
  const rangePct = high > low ? ((last - low) / (high - low)) * 100 : 50;
  return {
    changePct: first !== 0 ? ((last - first) / first) * 100 : 0,
    trend: classifyTrend(closes),
    rangePosition: classifyRange(rangePct),
    rangePct,
  };
}

export const TREND_LABELS: Record<TrendKind, string> = {
  up: '上昇基調',
  down: '下降基調',
  range: 'もみ合い',
};

export const TREND_DESCRIPTIONS: Record<TrendKind, string> = {
  up: `終値が${MA_WINDOW}本移動平均の上にあり、平均線も上向き`,
  down: `終値が${MA_WINDOW}本移動平均の下にあり、平均線も下向き`,
  range: `終値と${MA_WINDOW}本移動平均の関係に一貫した方向感がない`,
};

export const RANGE_LABELS: Record<RangePosition, string> = {
  high: '高値圏',
  middle: 'レンジ中位',
  low: '安値圏',
};

export interface TimeframeSet {
  // short=15分足、mid=60分足、long=日足。取得失敗・本数不足の足種は欠けてよい。
  short?: TimeframeInsight;
  mid?: TimeframeInsight;
  long?: TimeframeInsight;
}

function describeAlignment({ short, mid, long }: TimeframeSet): string | null {
  const available = [short, mid, long].filter((i): i is TimeframeInsight => i !== undefined);
  if (available.length >= 2 && available.every((i) => i.trend === 'up')) {
    return 'すべての時間軸で上昇基調がそろっており、短期から中期まで方向感が一致しています。';
  }
  if (available.length >= 2 && available.every((i) => i.trend === 'down')) {
    return 'すべての時間軸で下降基調がそろっており、短期から中期まで弱い流れが続いています。';
  }
  const shortTerm = short ?? mid;
  if (!long || !shortTerm) return null;
  if (long.trend === 'up' && shortTerm.trend === 'down') {
    return '日足は上昇基調ですが、短期足では下押しが見られます（上昇トレンド中の一時的な調整局面の形）。';
  }
  if (long.trend === 'down' && shortTerm.trend === 'up') {
    return '日足は下降基調ですが、短期足では反発が見られます（下降トレンド中の戻りの形）。';
  }
  return '時間軸によって方向感が分かれており、はっきりしたトレンドは出ていません。';
}

function describeLongRange(long: TimeframeInsight | undefined): string | null {
  if (!long) return null;
  const pct = Math.round(long.rangePct);
  if (long.rangePosition === 'high') return `日足では1年のレンジの上限付近（高値圏、レンジ内位置 ${pct}%）にあります。`;
  if (long.rangePosition === 'low') return `日足では1年のレンジの下限付近（安値圏、レンジ内位置 ${pct}%）にあります。`;
  return `日足では1年のレンジの中ほど（レンジ内位置 ${pct}%）にあります。`;
}

export function summarizeTimeframes(set: TimeframeSet): string[] {
  return [describeAlignment(set), describeLongRange(set.long)].filter((l): l is string => l !== null);
}
