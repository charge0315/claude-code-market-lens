import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { StockSearchBox } from '@/components/ui/StockSearchBox';
import { searchStocks } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockSearchStocks = searchStocks as jest.MockedFunction<typeof searchStocks>;

describe('StockSearchBox', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('入力すると検索結果を一覧表示する', async () => {
    mockSearchStocks.mockResolvedValue([{ code: '7203', name: 'トヨタ自動車', sector: '輸送用機器' }]);
    const user = userEvent.setup();

    render(<StockSearchBox onSelect={jest.fn()} />);
    await user.type(screen.getByLabelText('銘柄検索'), 'トヨタ');

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getByText('輸送用機器')).toBeInTheDocument();
  });

  it('結果をクリックするとonSelectを呼び入力欄をクリアする', async () => {
    mockSearchStocks.mockResolvedValue([{ code: '7203', name: 'トヨタ自動車', sector: null }]);
    const onSelect = jest.fn();
    const user = userEvent.setup();

    render(<StockSearchBox onSelect={onSelect} />);
    const input = screen.getByLabelText('銘柄検索');
    await user.type(input, 'トヨタ');
    await user.click(await screen.findByText('7203（トヨタ自動車）'));

    expect(onSelect).toHaveBeenCalledWith({ code: '7203', name: 'トヨタ自動車', sector: null });
    expect(input).toHaveValue('');
  });

  it('該当が無ければ空メッセージを出す', async () => {
    mockSearchStocks.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<StockSearchBox onSelect={jest.fn()} />);
    await user.type(screen.getByLabelText('銘柄検索'), 'xxxxx');

    expect(await screen.findByText('該当する銘柄がありません')).toBeInTheDocument();
  });

  it('検索失敗時はエラーメッセージを出す', async () => {
    mockSearchStocks.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<StockSearchBox onSelect={jest.fn()} />);
    await user.type(screen.getByLabelText('銘柄検索'), 'トヨタ');

    expect(await screen.findByText('銘柄検索に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<StockSearchBox onSelect={jest.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
