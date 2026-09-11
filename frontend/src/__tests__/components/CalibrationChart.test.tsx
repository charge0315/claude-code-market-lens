import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { CalibrationChart } from '@/components/model-lab/CalibrationChart';
import { fetchCalibration } from '@/lib/api/eval';
import type { CalibrationCurve } from '@/lib/api/eval';

jest.mock('@/lib/api/eval');

const mockFetchCalibration = fetchCalibration as jest.MockedFunction<typeof fetchCalibration>;

const CURVE: CalibrationCurve = {
  curve_id: 'c1',
  computed_at: '2026-06-01T00:00:00+09:00',
  scope: 'combined',
  horizon_days: 20,
  direction: null,
  points: [
    { p_pred: 0.6, p_obs: 0.58, n: 20 },
    { p_pred: 0.8, p_obs: 0.75, n: 15 },
  ],
  brier: 0.021,
  is_calibrated: 1,
};

describe('CalibrationChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchCalibration.mockResolvedValue(null);

    render(<CalibrationChart />);

    expect(await screen.findByText('データがありません（評価バッチ実行後に表示されます）')).toBeInTheDocument();
  });

  it('Brier スコアを表示する', async () => {
    mockFetchCalibration.mockResolvedValue(CURVE);

    render(<CalibrationChart />);

    expect(await screen.findByText('Brier: 0.0210')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchCalibration.mockRejectedValue(new Error('boom'));

    render(<CalibrationChart />);

    expect(await screen.findByText('較正曲線の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchCalibration.mockResolvedValue(CURVE);

    const { container } = render(<CalibrationChart />);
    await waitFor(() => expect(mockFetchCalibration).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
