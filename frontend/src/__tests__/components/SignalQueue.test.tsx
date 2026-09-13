import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { SignalQueue } from '@/components/portfolio/SignalQueue';
import { approveSignal, fetchSignals, rejectSignal, reportFill } from '@/lib/api/portfolio';
import type { PortfolioSignal, PortfolioSignalShadow } from '@/lib/api/portfolio';

jest.mock('@/lib/api/portfolio');

const mockFetchSignals = fetchSignals as jest.MockedFunction<typeof fetchSignals>;
const mockApproveSignal = approveSignal as jest.MockedFunction<typeof approveSignal>;
const mockRejectSignal = rejectSignal as jest.MockedFunction<typeof rejectSignal>;
const mockReportFill = reportFill as jest.MockedFunction<typeof reportFill>;

function makeSignal(overrides: Partial<PortfolioSignal> = {}): PortfolioSignal {
  return {
    signal_id: 's1',
    symbol: '7203',
    evaluated_at: '2026-06-02T10:00:00+09:00',
    action: 'trim',
    entry: null,
    stop: 2800,
    target: 3200,
    confidence: 72,
    rationale: 'RSIが70を超過し過熱感がある',
    status: 'proposed',
    fill_report: null,
    gemini_shadow: null,
    ...overrides,
  };
}

function makeGeminiShadow(overrides: Partial<PortfolioSignalShadow> = {}): PortfolioSignalShadow {
  return {
    shadow_id: 'sh1',
    signal_id: 's1',
    challenger_version: 'gemini:test',
    action: 'hold',
    entry: null,
    stop: 2750,
    target: 3300,
    confidence: 65,
    reasoning: 'テクニカル指標は中立圏で推移',
    created_at: '2026-06-02T10:00:00+09:00',
    ...overrides,
  };
}

describe('SignalQueue', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('該当が無ければ空メッセージを出す', async () => {
    mockFetchSignals.mockResolvedValue([]);

    render(<SignalQueue />);

    expect(await screen.findByText('該当する判定がありません')).toBeInTheDocument();
    expect(mockFetchSignals).toHaveBeenCalledWith({ status: 'proposed' });
  });

  it('proposed の判定に承認/却下ボタンを表示し、承認すると再取得する', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal()]);
    mockApproveSignal.mockResolvedValue({ signal_id: 's1', status: 'approved' });
    const user = userEvent.setup();

    render(<SignalQueue />);
    await screen.findByText('7203');

    await user.click(screen.getByRole('button', { name: '承認' }));

    await waitFor(() => expect(mockApproveSignal).toHaveBeenCalledWith('s1'));
    await waitFor(() => expect(mockFetchSignals).toHaveBeenCalledTimes(2));
  });

  it('却下ボタンで却下する', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal()]);
    mockRejectSignal.mockResolvedValue({ signal_id: 's1', status: 'rejected' });
    const user = userEvent.setup();

    render(<SignalQueue />);
    await screen.findByText('7203');
    const card = screen.getByRole('listitem');

    await user.click(within(card).getByRole('button', { name: '却下' }));

    await waitFor(() => expect(mockRejectSignal).toHaveBeenCalledWith('s1'));
  });

  it('タブ切り替えで状態別に再取得する', async () => {
    mockFetchSignals.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<SignalQueue />);
    await waitFor(() => expect(mockFetchSignals).toHaveBeenCalledWith({ status: 'proposed' }));

    await user.click(screen.getByRole('button', { name: 'すべて' }));

    await waitFor(() => expect(mockFetchSignals).toHaveBeenCalledWith(undefined));
  });

  it('approved の判定は実約定報告フォームを開いて送信できる', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal({ status: 'approved' })]);
    mockReportFill.mockResolvedValue({ signal_id: 's1', status: 'executed' });
    const user = userEvent.setup();

    render(<SignalQueue />);
    await user.click(await screen.findByRole('button', { name: '実約定を報告' }));

    await user.type(screen.getByLabelText('約定価格（円）'), '3050');
    await user.type(screen.getByLabelText('約定株数'), '30');
    await user.click(screen.getByRole('button', { name: '報告する' }));

    await waitFor(() =>
      expect(mockReportFill).toHaveBeenCalledWith(
        's1',
        expect.objectContaining({ executed_price: 3050, executed_quantity: 30 }),
      ),
    );
  });

  it('実約定報告フォームは不正な値を弾く', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal({ status: 'approved' })]);
    const user = userEvent.setup();

    render(<SignalQueue />);
    await user.click(await screen.findByRole('button', { name: '実約定を報告' }));

    await user.type(screen.getByLabelText('約定価格（円）'), '-5');
    await user.type(screen.getByLabelText('約定株数'), '10');
    await user.click(screen.getByRole('button', { name: '報告する' }));

    expect(await screen.findByText('約定価格は正の数値で入力してください')).toBeInTheDocument();
    expect(mockReportFill).not.toHaveBeenCalled();
  });

  it('executed かつ fill_report ありなら約定報告済みと表示する', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal({ status: 'executed', fill_report: '{}' })]);

    render(<SignalQueue />);

    expect(await screen.findByText('約定報告済み')).toBeInTheDocument();
  });

  it('Gemini shadow 判定があれば Claude の判定と併記する', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal({ gemini_shadow: makeGeminiShadow() })]);

    render(<SignalQueue />);

    expect(await screen.findByText('Claude')).toBeInTheDocument();
    expect(screen.getByText('Gemini（比較）')).toBeInTheDocument();
    expect(screen.getByText('テクニカル指標は中立圏で推移')).toBeInTheDocument();
  });

  it('Gemini shadow 判定が無ければ Claude の判定のみ表示する', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal()]);

    render(<SignalQueue />);

    await screen.findByText('7203');
    expect(screen.queryByText('Gemini（比較）')).not.toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchSignals.mockRejectedValue(new Error('boom'));

    render(<SignalQueue />);

    expect(await screen.findByText('判定一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchSignals.mockResolvedValue([makeSignal()]);

    const { container } = render(<SignalQueue />);
    await screen.findByText('7203');

    expect(await axe(container)).toHaveNoViolations();
  });
});
