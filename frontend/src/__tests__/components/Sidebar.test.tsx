import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { Sidebar } from '@/components/layout/Sidebar';

const ITEMS = [
  { href: '/dashboard', label: 'ダッシュボード' },
  { href: '/portfolio', label: 'ポートフォリオ' },
];

describe('Sidebar', () => {
  it('ナビゲーションリンクを表示する', () => {
    render(<Sidebar items={ITEMS} />);

    expect(screen.getByRole('link', { name: 'ダッシュボード' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ポートフォリオ' })).toBeInTheDocument();
  });

  it('トグルボタンで aria-expanded が切り替わる', async () => {
    const user = userEvent.setup();
    render(<Sidebar items={ITEMS} />);

    const toggle = screen.getByRole('button', { name: 'ナビゲーションを開く' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);

    expect(screen.getByRole('button', { name: 'ナビゲーションを閉じる' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('リンクをクリックすると開いた状態が閉じる', async () => {
    const user = userEvent.setup();
    render(<Sidebar items={ITEMS} />);

    await user.click(screen.getByRole('button', { name: 'ナビゲーションを開く' }));
    await user.click(screen.getByRole('link', { name: 'ポートフォリオ' }));

    expect(screen.getByRole('button', { name: 'ナビゲーションを開く' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('Escape キーで開いた状態が閉じる', async () => {
    const user = userEvent.setup();
    render(<Sidebar items={ITEMS} />);

    await user.click(screen.getByRole('button', { name: 'ナビゲーションを開く' }));
    await user.keyboard('{Escape}');

    expect(screen.getByRole('button', { name: 'ナビゲーションを開く' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<Sidebar items={ITEMS} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
