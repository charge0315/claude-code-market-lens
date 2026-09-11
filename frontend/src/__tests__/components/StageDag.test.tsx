import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { StageDag } from '@/components/pipeline/StageDag';
import type { StageStatus, StageName } from '@/lib/pipeline/types';

function stages(overrides: Partial<Record<StageName, StageStatus>>): Record<StageName, StageStatus> {
  return {
    collect: 'pending',
    subscore: 'pending',
    synthesis: 'pending',
    llm_overlay: 'pending',
    bracket: 'pending',
    verify: 'pending',
    ...overrides,
  };
}

describe('StageDag', () => {
  it('6 ステージすべてをラベル付きで表示する', () => {
    render(<StageDag snapshot={{ stages: stages({}), status: 'running' }} />);
    expect(screen.getByText('収集')).toBeInTheDocument();
    expect(screen.getByText('サブスコア')).toBeInTheDocument();
    expect(screen.getByText('合成')).toBeInTheDocument();
    expect(screen.getByText('LLM深掘り')).toBeInTheDocument();
    expect(screen.getByText('ブラケット')).toBeInTheDocument();
    expect(screen.getByText('検証')).toBeInTheDocument();
  });

  it('running ステージに aria-current="step" を付ける', () => {
    render(<StageDag snapshot={{ stages: stages({ collect: 'done', subscore: 'running' }), status: 'running' }} />);
    const running = screen.getByText('サブスコア').closest('.stage-node');
    expect(running).toHaveAttribute('aria-current', 'step');
  });

  it('done ステージの状態をスクリーンリーダ向けに伝える', () => {
    render(<StageDag snapshot={{ stages: stages({ collect: 'done' }), status: 'running' }} />);
    expect(screen.getByText('収集: 完了')).toBeInTheDocument();
  });

  it('failed ステージの状態を伝える', () => {
    render(<StageDag snapshot={{ stages: stages({ collect: 'failed' }), status: 'rejected' }} />);
    expect(screen.getByText('収集: 失敗')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(
      <StageDag snapshot={{ stages: stages({ collect: 'done', subscore: 'running' }), status: 'running' }} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
