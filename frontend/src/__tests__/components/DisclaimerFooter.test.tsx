import { render, screen } from '@testing-library/react';
import { DisclaimerFooter } from '@/components/DisclaimerFooter';

describe('DisclaimerFooter', () => {
  it('免責文言と「発注を一切行いません」を含む contentinfo を出す', () => {
    render(<DisclaimerFooter />);
    const footer = screen.getByRole('contentinfo');
    expect(footer).toHaveTextContent('分析結果・参考情報');
    expect(footer).toHaveTextContent('ブローカーへの発注を一切行いません');
  });
});
