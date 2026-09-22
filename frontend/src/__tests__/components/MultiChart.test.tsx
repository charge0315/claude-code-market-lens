import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { MultiChart } from '@/components/chart/MultiChart';
import { fetchOhlc } from '@/lib/api/stock';
import type { OhlcResponse } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

function response(overrides?: Partial<OhlcResponse>): OhlcResponse {
  return {
    bars: [{ time: '2026-06-01', open: 1000, high: 1020, low: 990, close: 1010, volume: 1_000_000 }],
    events: [],
    overlay: null,
    sub_indicator: null,
    ...overrides,
  };
}

describe('MultiChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('既存3足種（15分足/60分足/日足）それぞれの期間で取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    render(<MultiChart symbol="7203" />);

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1mo', '15m'));
    expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '3mo', '60m');
    expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1y', '1d');
    expect(mockFetchOhlc).toHaveBeenCalledTimes(3);
  });

  it('パネルの見出しを表示する', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    render(<MultiChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledTimes(3));

    expect(screen.getByText('15分足（1ヶ月）')).toBeInTheDocument();
    expect(screen.getByText('60分足（3ヶ月）')).toBeInTheDocument();
    expect(screen.getByText('日足（1年）')).toBeInTheDocument();
  });

  it('データが無いパネルには案内文を出す', async () => {
    mockFetchOhlc.mockResolvedValue(response({ bars: [] }));

    render(<MultiChart symbol="7203" />);

    expect(await screen.findAllByText('データがありません')).toHaveLength(3);
  });

  it('1つのパネルの取得が失敗しても他のパネルは影響を受けない', async () => {
    mockFetchOhlc.mockImplementation((_symbol, _period, interval) =>
      interval === '15m' ? Promise.reject(new Error('boom')) : Promise.resolve(response())
    );

    render(<MultiChart symbol="7203" />);

    expect(await screen.findByText('取得に失敗しました')).toBeInTheDocument();
    // 他の2パネルはエラーにならない（案内文・エラー文のいずれも出ない = 正常にデータ表示）。
    expect(screen.queryAllByText('取得に失敗しました')).toHaveLength(1);
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    const { container } = render(<MultiChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledTimes(3));

    expect(await axe(container)).toHaveNoViolations();
  });
});
