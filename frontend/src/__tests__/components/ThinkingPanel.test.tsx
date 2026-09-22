import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { ThinkingPanel } from '@/components/pipeline/ThinkingPanel';
import type { TraceEvent } from '@/lib/pipeline/types';

function event(overrides: Partial<TraceEvent>): TraceEvent {
  return {
    run_id: 'run-1',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'collect',
    stage_status: 'done',
    stage_seq: 1,
    payload: {},
    event_at: '2026-06-01T08:50:01+09:00',
    ...overrides,
  };
}

describe('ThinkingPanel', () => {
  it('イベントが無ければ案内文を出す', () => {
    render(<ThinkingPanel events={[]} />);
    expect(screen.getByText('まだイベントがありません')).toBeInTheDocument();
  });

  it('各ステージを日本語で要約する', () => {
    render(
      <ThinkingPanel
        events={[
          event({ stage: 'collect', stage_status: 'done', payload: { current_price: 1234.5 } }),
          event({
            stage: 'synthesis',
            stage_seq: 3,
            stage_status: 'done',
            payload: { composite_score: 62.1, direction: 'bullish' },
          }),
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: { should_include: true, confidence_raw: 72 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/現在値 1234.5 円を取得しました/)).toBeInTheDocument();
    expect(screen.getByText(/合成スコア 62.1/)).toBeInTheDocument();
    expect(screen.getByText(/確度（生値）72%/)).toBeInTheDocument();
  });

  it('LLM深掘りでポジティブなニュースセンチメントが判断材料になったことを表示する', () => {
    render(
      <ThinkingPanel
        events={[
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: {
              should_include: true,
              confidence_raw: 55,
              news_sentiment: { sentiment_label: 'positive', news_count: 8 },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/ニュース見出しのAIセンチメント判定「ポジティブ」（見出し8件）を判断材料に使用/)).toBeInTheDocument();
  });

  it('LLM深掘りでネガティブなニュースセンチメントが判断材料になったことを表示する', () => {
    render(
      <ThinkingPanel
        events={[
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: {
              should_include: true,
              confidence_raw: 42,
              news_sentiment: { sentiment_label: 'strongly_negative', news_count: 3 },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/ニュース見出しのAIセンチメント判定「強いネガティブ」（見出し3件）を判断材料に使用/)).toBeInTheDocument();
  });

  it('ニュースセンチメントが中立、または存在しない場合は追記しない', () => {
    render(
      <ThinkingPanel
        events={[
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: { should_include: true, confidence_raw: 60, news_sentiment: { sentiment_label: 'neutral', news_count: 5 } },
          }),
          event({
            stage: 'llm_overlay',
            stage_seq: 5,
            stage_status: 'done',
            payload: { should_include: true, confidence_raw: 60 },
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/を判断材料に使用/)).not.toBeInTheDocument();
  });

  it('LLM深掘りで信用倍率（買い長残優勢）が判断材料になったことを表示する', () => {
    render(
      <ThinkingPanel
        events={[
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: {
              should_include: true,
              confidence_raw: 55,
              supply_demand: { margin_ratio: 6.5, classification: 'long_heavy' },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/信用倍率 6.50倍（買い長残優勢）を判断材料に使用/)).toBeInTheDocument();
  });

  it('需給データが無い場合は追記しない', () => {
    render(
      <ThinkingPanel
        events={[
          event({
            stage: 'llm_overlay',
            stage_seq: 4,
            stage_status: 'done',
            payload: { should_include: true, confidence_raw: 60 },
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/信用倍率/)).not.toBeInTheDocument();
  });

  it('失敗ステージの理由を表示する', () => {
    render(
      <ThinkingPanel
        events={[event({ stage: 'bracket', stage_seq: 5, stage_status: 'failed', payload: { reason: '3値不整合' } })]}
      />,
    );
    expect(screen.getByText(/3 値不整合のため却下: 3値不整合/)).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(
      <ThinkingPanel events={[event({ payload: { current_price: 1000 } })]} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
