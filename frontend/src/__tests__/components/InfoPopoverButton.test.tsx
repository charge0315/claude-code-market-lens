import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { InfoPopoverButton } from '@/components/model-lab/InfoPopoverButton';

describe('InfoPopoverButton', () => {
  it('既定では説明を表示しない', () => {
    render(
      <InfoPopoverButton title="成長曲線とは">
        <p>詳しい説明本文</p>
      </InfoPopoverButton>,
    );
    expect(screen.queryByText('詳しい説明本文')).not.toBeInTheDocument();
  });

  it('？ボタンを押すと説明ポップアップを開き、閉じるボタンで閉じる', async () => {
    const user = userEvent.setup();
    render(
      <InfoPopoverButton title="成長曲線とは">
        <p>詳しい説明本文</p>
      </InfoPopoverButton>,
    );

    await user.click(screen.getByRole('button', { name: '成長曲線とはの詳しい説明を見る' }));
    expect(await screen.findByRole('heading', { name: '成長曲線とは' })).toBeInTheDocument();
    expect(screen.getByText('詳しい説明本文')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '閉じる' }));
    expect(screen.queryByText('詳しい説明本文')).not.toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <InfoPopoverButton title="成長曲線とは">
        <p>詳しい説明本文</p>
      </InfoPopoverButton>,
    );
    await user.click(screen.getByRole('button', { name: '成長曲線とはの詳しい説明を見る' }));
    expect(await axe(container)).toHaveNoViolations();
  });
});
