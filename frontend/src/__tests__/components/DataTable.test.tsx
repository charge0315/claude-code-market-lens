import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { DataTable, type Column } from '@/components/ui/DataTable';

interface Pick {
  symbol: string;
  confidence: number;
}

const columns: ReadonlyArray<Column<Pick>> = [
  { key: 'symbol', header: '銘柄コード' },
  { key: 'confidence', header: '確度', numeric: true, render: (r) => r.confidence.toFixed(1) },
];

describe('DataTable', () => {
  it('caption と行データをレンダリングする', () => {
    render(
      <DataTable
        caption="本日の中長期ピック"
        columns={columns}
        rows={[
          { symbol: '7203', confidence: 82.4 },
          { symbol: '6758', confidence: 61 },
        ]}
        rowKey={(r) => r.symbol}
      />,
    );
    expect(screen.getByRole('table', { name: '本日の中長期ピック' })).toBeInTheDocument();
    expect(screen.getByText('7203')).toBeInTheDocument();
    expect(screen.getByText('82.4')).toBeInTheDocument();
  });

  it('行が空なら emptyMessage を出す', () => {
    render(
      <DataTable
        caption="空の表"
        columns={columns}
        rows={[]}
        rowKey={(r) => r.symbol}
        emptyMessage="ピックはありません"
      />,
    );
    expect(screen.getByText('ピックはありません')).toBeInTheDocument();
  });

  it('数値列は num クラス（等幅・右寄せ）を持つ', () => {
    render(
      <DataTable
        caption="数値列の検証"
        columns={columns}
        rows={[{ symbol: '7203', confidence: 82.4 }]}
        rowKey={(r) => r.symbol}
      />,
    );
    expect(screen.getByText('82.4')).toHaveClass('num');
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(
      <DataTable
        caption="a11y 検証"
        columns={columns}
        rows={[{ symbol: '7203', confidence: 82.4 }]}
        rowKey={(r) => r.symbol}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
