import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PageShell } from '@/components/ui/PageShell';

describe('PageShell', () => {
  it('タイトルと子要素を表示する', () => {
    render(
      <PageShell title="ダッシュボード">
        <p>子要素</p>
      </PageShell>,
    );

    expect(screen.getByRole('heading', { level: 1, name: 'ダッシュボード' })).toBeInTheDocument();
    expect(screen.getByText('子要素')).toBeInTheDocument();
  });

  it('badge を渡すと見出し横に表示する', () => {
    render(<PageShell title="モデルラボ" badge="自動学習ダッシュボード" />);

    expect(screen.getByText('自動学習ダッシュボード')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<PageShell title="ダッシュボード" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
