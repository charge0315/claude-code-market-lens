import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { EquityCurveChart } from '@/components/model-lab/EquityCurveChart';
import { fetchEquityCurve } from '@/lib/api/eval';
import type { EquityCurveResult } from '@/lib/api/eval';

jest.mock('@/lib/api/eval');

const mockFetchEquityCurve = fetchEquityCurve as jest.MockedFunction<typeof fetchEquityCurve>;

const RESULT: EquityCurveResult = {
  scope: 'combined',
  horizon_days: 20,
  n: 3,
  equity: [1.01, 1.02, 0.99],
  max_drawdown: 0.03,
  sharpe: 1.2,
  win_rate: 0.6,
};

describe('EquityCurveChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchEquityCurve.mockResolvedValue({ ...RESULT, n: 0, equity: [] });

    render(<EquityCurveChart />);

    expect(await screen.findByText('決着済みピックがまだありません')).toBeInTheDocument();
  });

  it('n・最大DD・Sharpe・勝率を表示する', async () => {
    mockFetchEquityCurve.mockResolvedValue(RESULT);

    render(<EquityCurveChart />);

    expect(await screen.findByText(/n=3/)).toBeInTheDocument();
    expect(screen.getByText(/最大DD 3.0%/)).toBeInTheDocument();
    expect(screen.getByText(/Sharpe 1.20/)).toBeInTheDocument();
    expect(screen.getByText(/60.0%/)).toBeInTheDocument();
  });

  it('scope / ホライズンを切り替えると再取得する', async () => {
    mockFetchEquityCurve.mockResolvedValue(RESULT);
    const user = userEvent.setup();

    render(<EquityCurveChart />);
    await waitFor(() => expect(mockFetchEquityCurve).toHaveBeenCalledWith('combined', 20));

    await user.selectOptions(screen.getByLabelText('scope'), '短期');
    await waitFor(() => expect(mockFetchEquityCurve).toHaveBeenCalledWith('short_term', 20));

    await user.selectOptions(screen.getByLabelText('ホライズン'), '60営業日');
    await waitFor(() => expect(mockFetchEquityCurve).toHaveBeenCalledWith('short_term', 60));
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchEquityCurve.mockRejectedValue(new Error('boom'));

    render(<EquityCurveChart />);

    expect(await screen.findByText('エクイティカーブの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchEquityCurve.mockResolvedValue(RESULT);

    const { container } = render(<EquityCurveChart />);
    await waitFor(() => expect(mockFetchEquityCurve).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
