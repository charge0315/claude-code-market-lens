import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ModelLabTabs } from '@/components/model-lab/ModelLabTabs';

describe('ModelLabTabs', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('既定では「かんたん」タブを表示する', () => {
    render(<ModelLabTabs simple={<p>かんたん内容</p>} advanced={<p>詳細内容</p>} />);

    expect(screen.getByText('かんたん内容')).toBeVisible();
    expect(screen.getByText('詳細内容')).not.toBeVisible();
  });

  it('「詳細」タブへ切り替えると保存され、次のレンダーでも復元される', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ModelLabTabs simple={<p>かんたん内容</p>} advanced={<p>詳細内容</p>} />);

    await user.click(screen.getByRole('tab', { name: '詳細' }));
    expect(screen.getByText('詳細内容')).toBeVisible();
    expect(screen.getByText('かんたん内容')).not.toBeVisible();

    unmount();
    render(<ModelLabTabs simple={<p>かんたん内容</p>} advanced={<p>詳細内容</p>} />);
    expect(screen.getByText('詳細内容')).toBeVisible();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<ModelLabTabs simple={<p>かんたん内容</p>} advanced={<p>詳細内容</p>} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
