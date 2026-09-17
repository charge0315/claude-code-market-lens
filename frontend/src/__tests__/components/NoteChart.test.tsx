import { render } from '@testing-library/react';
import { NoteChart, noteChartColor } from '@/components/notes/NoteChart';

describe('NoteChart', () => {
  it('タイトル・件数をaria-labelへ含める', () => {
    const { getByRole } = render(<NoteChart title="7203（トヨタ自動車）" values={[100, 110, 105]} />);

    expect(getByRole('img', { name: '7203（トヨタ自動車）の値動きチャート（直近3日分）' })).toBeInTheDocument();
  });

  it('値が1件以下なら何も描画しない', () => {
    const { container } = render(<NoteChart title="7203" values={[100]} />);

    expect(container.querySelector('svg')).toBeNull();
  });

  it('entry/stop/targetに相当する価格ラベルは含めず、系列の最大/最小のみを表示する', () => {
    const { container } = render(<NoteChart title="7203" values={[100, 200, 150]} />);

    expect(container.textContent).toContain('200');
    expect(container.textContent).toContain('100');
  });
});

describe('noteChartColor', () => {
  it('上昇なら赤系（国内証券基準）を返す', () => {
    expect(noteChartColor([100, 110])).toBe('#b32424');
  });

  it('下落なら緑系を返す', () => {
    expect(noteChartColor([110, 100])).toBe('#1f6b3a');
  });

  it('横ばい・データ不足ならニュートラル色を返す', () => {
    expect(noteChartColor([100, 100])).toBe('#6b675f');
    expect(noteChartColor([100])).toBe('#6b675f');
  });
});
