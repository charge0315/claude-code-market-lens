import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ChartSymbolSearch } from '@/components/chart/ChartSymbolSearch';
import { searchStocks } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

const mockSearchStocks = searchStocks as jest.MockedFunction<typeof searchStocks>;

describe('ChartSymbolSearch', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄を選択するとチャート画面へ遷移する', async () => {
    mockSearchStocks.mockResolvedValue([{ code: '7203', name: 'トヨタ自動車', sector: '輸送用機器' }]);
    const user = userEvent.setup();

    render(<ChartSymbolSearch />);
    await user.type(screen.getByLabelText('銘柄検索'), 'トヨタ');
    await user.click(await screen.findByText('7203（トヨタ自動車）'));

    expect(mockPush).toHaveBeenCalledWith('/chart?symbol=7203');
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<ChartSymbolSearch />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
