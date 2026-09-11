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
      return `AI 深掘り完了（確度（生値）${num(p.confidence_raw, 0) ?? '—'}%）`;
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
