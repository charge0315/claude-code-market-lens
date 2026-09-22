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
const DEAD_CROSS: ChartEvent = { date: '2026-06-01', kind: 'dead_cross', label: 'デッドクロス（下降トレンド転換の兆候です。）' };

function response(overrides?: Partial<OhlcResponse>): OhlcResponse {
  return { bars: [BAR], events: [], overlay: null, sub_indicator: null, ...overrides };
}

describe('PriceChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄の OHLC を取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    render(<PriceChart symbol="7203" />);

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', undefined, undefined));
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchOhlc.mockResolvedValue(response({ bars: [] }));

    render(<PriceChart symbol="7203" />);

    expect(await screen.findByText('株価データがありません')).toBeInTheDocument();
  });

  it('期間ボタンを切り替えると再取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', undefined, undefined));

    await user.click(screen.getByRole('button', { name: '1年' }));

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1y', '1d', undefined, undefined));
  });

  it('enableAdvancedControls が無ければ足種・指標セレクタを表示しない', async () => {
    mockFetchOhlc.mockResolvedValue(response());

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(screen.queryByRole('group', { name: '足種' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'オーバーレイ指標' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'サブインジケーター' })).not.toBeInTheDocument();
  });

  it('enableAdvancedControls があれば足種セレクタを表示し、切り替えると再取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" enableAdvancedControls />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', undefined));

    await user.click(screen.getByRole('button', { name: '60分足' }));

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '60m', 'sma', undefined));
  });

  it('分足へ切り替えるとその足種で選べない期間ボタンが消え、選べる期間へ丸める', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" enableAdvancedControls />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', undefined));

    await user.click(screen.getByRole('button', { name: '15分足' }));

    // 15分足は '1mo' しか選べないため、期間は自動的に '1ヶ月' へ丸まり他の期間ボタンは消える。
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1mo', '15m', 'sma', undefined));
    expect(screen.queryByRole('button', { name: '6ヶ月' })).not.toBeInTheDocument();
  });

  it('オーバーレイ指標ボタンを切り替えると再取得する', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" enableAdvancedControls />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', undefined));

    await user.click(screen.getByRole('button', { name: '一目均衡表' }));

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'ichimoku', undefined));
  });

  it('サブインジケーターボタンを切り替えると再取得する（出来高はバックエンドへ問い合わせない）', async () => {
    mockFetchOhlc.mockResolvedValue(response());
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" enableAdvancedControls />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', undefined));

    await user.click(screen.getByRole('button', { name: 'RSI' }));
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', 'rsi'));

    await user.click(screen.getByRole('button', { name: '出来高' }));
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d', 'sma', undefined));
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

  it('ゴールデンクロスのツールチップは種別見出しとdata-signal="bullish"で強調される', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [GOLDEN_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    act(() => {
      __emitCrosshairMove({ time: '2026-06-01', point: { x: 120, y: 40 } });
    });

    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveAttribute('data-signal', 'bullish');
    expect(tooltip).toHaveTextContent('ゴールデンクロス');
  });

  it('デッドクロスのツールチップは種別見出しとdata-signal="bearish"で強調される', async () => {
    mockFetchOhlc.mockResolvedValue(response({ events: [DEAD_CROSS] }));

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    act(() => {
      __emitCrosshairMove({ time: '2026-06-01', point: { x: 120, y: 40 } });
    });

    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveAttribute('data-signal', 'bearish');
    expect(tooltip).toHaveTextContent('デッドクロス');
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

  it('enableAdvancedControls込みでもアクセシビリティ違反がない', async () => {
    mockFetchOhlc.mockResolvedValue(
      response({
        overlay: { kind: 'sma', lines: { SMA_5: [{ time: '2026-06-01', value: 1000 }] } },
      })
    );

    const { container } = render(<PriceChart symbol="7203" enableAdvancedControls />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
