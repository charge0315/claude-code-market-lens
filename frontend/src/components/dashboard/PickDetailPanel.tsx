'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { PriceChart } from '@/components/stock-detail/PriceChart';
import { fetchPickDetail, type Direction, type PickDetail, type SubScores } from '@/lib/api/picks';
import './dashboard.css';

// ピック詳細スライドインパネルの中身（🆕 P13、参照デザイン準拠）。
// 3値カード → ローソク足チャート（既存 PriceChart をそのまま埋め込み）→ 根拠概要 →
// 4分析カード（sub_scores + source_contributions 由来、LLM スキーマは変更しない）→
// 留意点 → 他 LLM 判定（P12）→ フッタ の順で構成する。

const DIRECTION_LABELS: Record<Direction, string> = { bullish: '強気', bearish: '弱気', neutral: '中立' };

const CATEGORY_LABELS: Record<keyof SubScores, string> = {
  technical: 'テクニカル',
  trend: 'トレンド',
  fundamental: 'ファンダメンタル',
  sentiment: 'センチメント',
};

function directionColor(direction: Direction): string {
  if (direction === 'bullish') return 'var(--color-gain)';
  if (direction === 'bearish') return 'var(--color-loss)';
  return 'var(--color-flat)';
}

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

// shadow_predictions.challenger_version は `"gemini:<モデル名>"` 形式で保存される
// （`orchestrator.py`）。ラベル用に「Gemini（モデル名）」の形へ整形する。
function formatEngineLabel(challengerVersion: string): string {
  const [engine, ...rest] = challengerVersion.split(':');
  const model = rest.join(':');
  if (engine.toLowerCase() === 'gemini' && model) return `Gemini（${model}）`;
  return challengerVersion;
}

function deviationFromCurrent(value: number, currentPrice: number | null): string | null {
  if (currentPrice === null || currentPrice === 0) return null;
  const pct = ((value - currentPrice) / currentPrice) * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
}

interface Contribution {
  weight_share: number;
  contribution: number;
}

function contributionFor(category: string, sourceContributions: Record<string, unknown>): Contribution | null {
  const raw = sourceContributions[category];
  if (
    raw !== null &&
    typeof raw === 'object' &&
    'weight_share' in raw &&
    'contribution' in raw &&
    typeof (raw as Record<string, unknown>).weight_share === 'number' &&
    typeof (raw as Record<string, unknown>).contribution === 'number'
  ) {
    const r = raw as Record<string, unknown>;
    return { weight_share: r.weight_share as number, contribution: r.contribution as number };
  }
  return null;
}

export function PickDetailPanel({ pickId }: { pickId: string }): ReactNode {
  const [detail, setDetail] = useState<PickDetail | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPickDetail(pickId)
      .then(setDetail)
      .catch(() => setError('ピック詳細の取得に失敗しました'));
  }, [pickId]);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (detail === undefined) return <p>読み込み中…</p>;
  if (detail === null) return <p className="signal-queue-empty">詳細が見つかりません</p>;

  const riskFactors = detail.rationale_struct.llm_risk_factors;
  const holdingDays = detail.rationale_struct.holding_period_days;
  const categories = Object.keys(CATEGORY_LABELS) as (keyof SubScores)[];

  return (
    <div className="pick-detail-body">
      <div className="pick-detail-price-header">
        <span className="pick-detail-price">{detail.current_price === null ? '—' : formatYen(detail.current_price)}</span>
        {detail.change_pct !== null && (
          <span style={{ color: directionColor(detail.change_pct >= 0 ? 'bullish' : 'bearish') }}>
            {detail.change_pct >= 0 ? '+' : ''}
            {detail.change_pct.toFixed(2)}%
          </span>
        )}
      </div>

      <div className="pick-detail-bracket-row">
        <div className="pick-detail-bracket-card">
          <span className="pick-detail-bracket-label">推奨買値</span>
          <span className="pick-detail-bracket-value">{formatYen(detail.entry)}</span>
          {deviationFromCurrent(detail.entry, detail.current_price) && (
            <span className="pick-detail-bracket-note">{deviationFromCurrent(detail.entry, detail.current_price)}</span>
          )}
        </div>
        <div className="pick-detail-bracket-card">
          <span className="pick-detail-bracket-label">推奨損切値</span>
          <span className="pick-detail-bracket-value">{formatYen(detail.stop)}</span>
          {deviationFromCurrent(detail.stop, detail.current_price) && (
            <span className="pick-detail-bracket-note">{deviationFromCurrent(detail.stop, detail.current_price)}</span>
          )}
        </div>
        <div className="pick-detail-bracket-card">
          <span className="pick-detail-bracket-label">推奨売値</span>
          <span className="pick-detail-bracket-value">{formatYen(detail.target)}</span>
          {deviationFromCurrent(detail.target, detail.current_price) && (
            <span className="pick-detail-bracket-note">{deviationFromCurrent(detail.target, detail.current_price)}</span>
          )}
        </div>
      </div>

      <h3 className="pick-detail-subheading">ローソク足チャート</h3>
      <PriceChart symbol={detail.symbol} />

      <h3 className="pick-detail-subheading">ピックアップ根拠</h3>
      <p>{detail.rationale_text}</p>

      <h3 className="pick-detail-subheading">4分析内訳</h3>
      <div className="pick-detail-category-grid">
        {categories.map((category) => {
          const contribution = contributionFor(category, detail.source_contributions);
          return (
            <div key={category} className="pick-detail-category-card">
              <span className="pick-detail-category-label">{CATEGORY_LABELS[category]}</span>
              <span className="pick-detail-category-score">{detail.sub_scores[category].toFixed(0)}</span>
              {contribution && (
                <span className="pick-detail-category-note">
                  合成スコア寄与 {contribution.contribution.toFixed(1)}
                  （重み {(contribution.weight_share * 100).toFixed(0)}%）
                </span>
              )}
            </div>
          );
        })}
      </div>

      {Array.isArray(riskFactors) && riskFactors.length > 0 && (
        <>
          <h3 className="pick-detail-subheading">留意点</h3>
          <ul>
            {riskFactors.map((factor, i) => (

              <li key={i}>{String(factor)}</li>
            ))}
          </ul>
        </>
      )}
      {typeof holdingDays === 'number' && <p className="model-lab-brier">想定保有期間: 約{holdingDays}営業日</p>}

      {detail.shadow_predictions.length > 0 && (
        <>
          <h3 className="pick-detail-subheading">他の LLM による判定（参考、比較用）</h3>
          <ul className="pick-detail-shadow-list">
            {detail.shadow_predictions.map((shadow) => (
              <li key={shadow.shadow_id} className="pick-detail-shadow-item">
                <p className="pick-detail-shadow-header">
                  <span>{formatEngineLabel(shadow.challenger_version)}</span>
                  <span style={{ color: directionColor(shadow.direction) }}>
                    {DIRECTION_LABELS[shadow.direction]}（確度 {shadow.confidence.toFixed(0)}）
                  </span>
                </p>
                <p className="pick-detail-shadow-bracket">
                  買値 {formatYen(shadow.entry)} / 損切値 {formatYen(shadow.stop)} / 売値 {formatYen(shadow.target)}
                </p>
                {shadow.reasoning && <p>{shadow.reasoning}</p>}
                {shadow.risk_factors.length > 0 && (
                  <ul>
                    {shadow.risk_factors.map((factor, i) => (

                      <li key={i}>{factor}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="pick-detail-footer">
        スコア {detail.composite_score.toFixed(1)} / 抽出日時 {detail.issued_at.slice(0, 16).replace('T', ' ')} / 生成AI Claude
        （モデル {detail.model_version}）
      </p>
    </div>
  );
}
