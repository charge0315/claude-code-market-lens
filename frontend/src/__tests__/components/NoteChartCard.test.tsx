import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NoteChartCard } from '@/components/notes/NoteChartCard';
import { downloadSvgAsPng } from '@/lib/exportChartImage';

jest.mock('@/lib/exportChartImage');

const mockDownloadSvgAsPng = downloadSvgAsPng as jest.MockedFunction<typeof downloadSvgAsPng>;

describe('NoteChartCard', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄コード・社名をタイトルに表示する', () => {
    render(<NoteChartCard symbol="7203" companyName="トヨタ自動車" values={[100, 110, 105]} />);

    expect(screen.getByRole('img', { name: /7203（トヨタ自動車）/ })).toBeInTheDocument();
  });

  it('画像として保存ボタンでdownloadSvgAsPngを呼び、完了表示に変わる', async () => {
    mockDownloadSvgAsPng.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<NoteChartCard symbol="7203" companyName="トヨタ自動車" values={[100, 110, 105]} />);
    await user.click(screen.getByRole('button', { name: '画像として保存' }));

    expect(mockDownloadSvgAsPng).toHaveBeenCalledWith(expect.anything(), '7203_chart.png');
    expect(await screen.findByRole('button', { name: '保存しました' })).toBeInTheDocument();
  });

  it('書き出し失敗時はエラーメッセージを出す', async () => {
    mockDownloadSvgAsPng.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<NoteChartCard symbol="7203" companyName="トヨタ自動車" values={[100, 110, 105]} />);
    await user.click(screen.getByRole('button', { name: '画像として保存' }));

    expect(await screen.findByText(/画像の書き出しに失敗しました/)).toBeInTheDocument();
  });
});
