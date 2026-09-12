import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { BeginnerIntro } from '@/components/model-lab/BeginnerIntro';

describe('BeginnerIntro', () => {
  it('モデルラボの説明見出しを表示する', () => {
    render(<BeginnerIntro />);
    expect(screen.getByRole('heading', { name: 'モデルラボとは？' })).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<BeginnerIntro />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
