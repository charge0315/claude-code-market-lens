import { render } from '@testing-library/react';
import { Sparkline } from '@/components/ui/Sparkline';

describe('Sparkline', () => {
  it('2点未満では何も描画しない', () => {
    const { container } = render(<Sparkline values={[100]} color="red" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('値の数だけ折れ線の点を打つ', () => {
    const { container } = render(<Sparkline values={[100, 110, 90, 120]} color="red" />);
    const polyline = container.querySelector('polyline');
    expect(polyline).not.toBeNull();
    expect(polyline?.getAttribute('points')?.split(' ')).toHaveLength(4);
    expect(polyline?.getAttribute('stroke')).toBe('red');
  });

  it('すべて同じ値でもゼロ除算せず描画する', () => {
    const { container } = render(<Sparkline values={[100, 100, 100]} color="red" />);
    expect(container.querySelector('polyline')).not.toBeNull();
  });
});
