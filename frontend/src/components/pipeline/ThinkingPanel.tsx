import type { ReactNode } from 'react';
import { STAGE_LABELS, type TraceEvent } from '@/lib/pipeline/types';
import './pipeline.css';

// ステージ遷移イベントを時系列ログとして表示する（「AI が今何を考えているか」の実況）。
// payload の生 JSON は出さず、ステージごとに意味のある日本語1行へ要約する。

interface ThinkingPanelProps {
  events: readonly TraceEvent[];
}

function num(value: unknown, digits = 1): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : null;
}

// ニュース見出しAIセンチメント（`llm_overlay` payload の `news_sentiment`、
// `LlmNewsSentimentResult.to_rationale_dict()` 形状）の判定ラベル。中立は判断材料として
// 言及する価値が薄いため、ポジティブ/ネガティブ方向のときだけ1行に追記する。
const NEWS_SENTIMENT_LABELS: Record<string, string> = {
  strongly_positive: '強いポジティブ',
  positive: 'ポジティブ',
  negative: 'ネガティブ',
  strongly_negative: '強いネガティブ',
};

function newsSentimentNote(payload: Record<string, unknown>): string {
  const raw = payload.news_sentiment;
  if (raw === null || typeof raw !== 'object') return '';
  const sentiment = raw as Record<string, unknown>;
  const label = typeof sentiment.sentiment_label === 'string' ? NEWS_SENTIMENT_LABELS[sentiment.sentiment_label] : undefined;
  if (label === undefined) return '';
  const newsCount = num(sentiment.news_count, 0);
  return `。ニュース見出しのAIセンチメント判定「${label}」（見出し${newsCount ?? '—'}件）を判断材料に使用`;
}

// 週末信用取引残高（`llm_overlay` payload の `supply_demand`、中長期ピック限定）。
const SUPPLY_DEMAND_LABELS: Record<string, string> = {
  long_heavy: '買い長残優勢',
  short_heavy: '売り長残優勢',
  balanced: '均衡',
};

function supplyDemandNote(payload: Record<string, unknown>): string {
  const raw = payload.supply_demand;
  if (raw === null || typeof raw !== 'object') return '';
  const supplyDemand = raw as Record<string, unknown>;
  const label =
    typeof supplyDemand.classification === 'string' ? SUPPLY_DEMAND_LABELS[supplyDemand.classification] : undefined;
  const ratio = num(supplyDemand.margin_ratio, 2);
  if (label === undefined || ratio === null) return '';
  return `。信用倍率 ${ratio}倍（${label}）を判断材料に使用`;
}

function summarize(event: TraceEvent): string {
  const p = event.payload;
  const failed = event.stage_status === 'failed';

  switch (event.stage) {
    case 'collect':
      return failed ? '現在値を取得できませんでした' : `現在値 ${num(p.current_price) ?? '—'} 円を取得しました`;
    case 'subscore':
      return 'テクニカル / トレンド / ファンダメンタル / センチメントのサブスコアを算出しました';
    case 'synthesis':
      return `合成スコア ${num(p.composite_score) ?? '—'}（方向: ${String(p.direction ?? '不明')}）`;
    case 'llm_overlay':
      if (failed) return 'AI の応答が不正な形式でした';
      if (p.should_include === false) return 'AI が対象外と判断しました';
      return `AI 深掘り完了（確度（生値）${num(p.confidence_raw, 0) ?? '—'}%）${newsSentimentNote(p)}${supplyDemandNote(p)}`;
    case 'bracket':
      if (failed) return `3 値不整合のため却下: ${String(p.reason ?? '')}`;
      return `買値 ${num(p.entry, 0) ?? '—'} / 損切 ${num(p.stop, 0) ?? '—'} / 売値 ${num(p.target, 0) ?? '—'} を確定`;
    case 'verify':
      if (failed) return String(p.reason ?? '検証で却下されました');
      return `確度 ${num(p.confidence, 0) ?? '—'}%（${String(p.confidence_bucket ?? '')}）で確定しました`;
    default:
      return '';
  }
}

export function ThinkingPanel({ events }: ThinkingPanelProps): ReactNode {
  return (
    <ol className="thinking-panel" aria-label="AI の思考ログ">
      {events.length === 0 && <li className="thinking-panel-empty">まだイベントがありません</li>}
      {events.map((e) => (
        <li key={e.trace_id ?? `${e.stage}-${e.stage_seq}`} className={`thinking-entry thinking-entry--${e.stage_status}`}>
          <span className="thinking-entry-stage">{STAGE_LABELS[e.stage]}</span>
          <span className="thinking-entry-text">{summarize(e)}</span>
          <span className="thinking-entry-time num">{e.event_at.slice(11, 19)}</span>
        </li>
      ))}
    </ol>
  );
}
