import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { __emitCrosshairMove } from '@/__tests__/__mocks__/lightweightCharts';
import { PriceChart } from '@/components/stock-detail/PriceChart';
import { fetchOhlc } from '@/lib/api/stock';
import type { ChartEvent, OhlcBar, OhlcResponse } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

const BAR: OhlcBar = { time: '2026-06-01', open: 1000, high: 1020, low: 990, close: 1010, volume: 1_000_000 };
const GOLDEN_CROSS: ChartEvent = { date: '2026-06-01', kind: 'golden_cross', label: 'ゴールデンクロス（上昇トレンド転換の兆候です。）' };

function response(overrides?: Partial<OhlcResponse>): OhlcResponse {
  return { bars: [BAR], events: [], ...overrides };
}

describe('PriceChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄の OHLC を取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    render(<PriceChart symbol="7203" />);

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo'));
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchOhlc.mockResolvedValue({ bars: [], events: [] });

    render(<PriceChart symbol="7203" />);

    expect(await screen.findByText('株価データがありません')).toBeInTheDocument();
  });

  it('期間ボタンを切り替えると再取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo'));

    await user.click(screen.getByRole('button', { name: '1年' }));

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1y'));
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchOhlc.mockRejectedValue(new Error('boom'));

    render(<PriceChart symbol="7203" />);

    expect(await screen.findByText('株価データの取得に失敗しました')).toBeInTheDocument();
  });

  it('兆候イベントが無ければツールチップを表示しない', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('兆候イベントを取得してもcrosshair移動前はツールチップを表示しない', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [GOLDEN_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('マーカーの立つ日付にhoverすると兆候の説明をツールチップで表示する', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [GOLDEN_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    act(() => {
      __emitCrosshairMove({ time: '2026-06-01', point: { x: 120, y: 40 } });
    });

    expect(await screen.findByRole('tooltip')).toHaveTextContent(GOLDEN_CROSS.label);
  });

  it('BusinessDay形式のtimeでも日付を突き合わせてツールチップを表示する', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [GOLDEN_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    act(() => {
      __emitCrosshairMove({ time: { year: 2026, month: 6, day: 1 }, point: { x: 120, y: 40 } });
    });

    expect(await screen.findByRole('tooltip')).toHaveTextContent(GOLDEN_CROSS.label);
  });

  it('兆候の無い日付へhoverが移るとツールチップを隠す', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [GOLDEN_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    act(() => {
      __emitCrosshairMove({ time: '2026-06-01', point: { x: 120, y: 40 } });
    });
    await screen.findByRole('tooltip');

    act(() => {
      __emitCrosshairMove({ time: '2026-06-02', point: { x: 150, y: 40 } });
    });

    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    const { container } = render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
