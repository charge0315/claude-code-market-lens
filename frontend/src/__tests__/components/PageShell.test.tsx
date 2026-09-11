import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PageShell } from '@/components/ui/PageShell';

describe('PageShell', () => {
  it('タイトルとフェーズ表示、子要素を表示する', () => {
    render(
      <PageShell title="ダッシュボード" phase="P8">
        <p>子要素</p>
      </PageShell>,
    );

    expect(screen.getByRole('heading', { level: 1, name: 'ダッシュボード' })).toBeInTheDocument();
    expect(screen.getByText('P8 で実装予定')).toBeInTheDocument();
    expect(screen.getByText('子要素')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<PageShell title="ダッシュボード" phase="P8" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
