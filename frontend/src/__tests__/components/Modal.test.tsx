import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { Modal } from '@/components/ui/Modal';

describe('Modal', () => {
  it('タイトルと子要素を表示する', () => {
    render(
      <Modal title="テストタイトル" onClose={jest.fn()}>
        <p>本文</p>
      </Modal>,
    );

    expect(screen.getByText('テストタイトル')).toBeInTheDocument();
    expect(screen.getByText('本文')).toBeInTheDocument();
  });

  it('閉じるボタンクリックで onClose を呼ぶ', async () => {
    const onClose = jest.fn();
    const user = userEvent.setup();
    render(
      <Modal title="x" onClose={onClose}>
        本文
      </Modal>,
    );

    await user.click(screen.getByRole('button', { name: '閉じる' }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape キーで onClose を呼ぶ', async () => {
    const onClose = jest.fn();
    const user = userEvent.setup();
    render(
      <Modal title="x" onClose={onClose}>
        本文
      </Modal>,
    );

    await user.keyboard('{Escape}');

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('バックドロップクリックで onClose を呼ぶがコンテンツ内クリックでは呼ばない', async () => {
    const onClose = jest.fn();
    const user = userEvent.setup();
    render(
      <Modal title="x" onClose={onClose}>
        <p>本文</p>
      </Modal>,
    );

    await user.click(screen.getByText('本文'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(
      <Modal title="テストタイトル" onClose={jest.fn()}>
        本文
      </Modal>,
    );

    expect(await axe(container)).toHaveNoViolations();
  });

  it('🆕 P13: variant="panel" では is-panel クラスが付与される', () => {
    const { container } = render(
      <Modal title="詳細" onClose={jest.fn()} variant="panel">
        本文
      </Modal>,
    );

    expect(container.querySelector('.modal-backdrop.is-panel')).toBeInTheDocument();
    expect(container.querySelector('.modal-content.is-panel')).toBeInTheDocument();
  });

  it('既定（center）では is-panel クラスが付与されない', () => {
    const { container } = render(
      <Modal title="詳細" onClose={jest.fn()}>
        本文
      </Modal>,
    );

    expect(container.querySelector('.is-panel')).not.toBeInTheDocument();
  });
});
