import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { PicksBoard } from '@/components/dashboard/PicksBoard';
import { fetchPickDetail, fetchPicks, runPicks } from '@/lib/api/picks';
import { fetchStockNote } from '@/lib/api/stock';
import type { PickDetail, PickSummary } from '@/lib/api/picks';

jest.mock('@/lib/api/picks');
jest.mock('@/lib/api/stock');

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockRunPicks = runPicks as jest.MockedFunction<typeof runPicks>;
const mockFetchPickDetail = fetchPickDetail as jest.MockedFunction<typeof fetchPickDetail>;
const mockFetchStockNote = fetchStockNote as jest.MockedFunction<typeof fetchStockNote>;

const PICK_DETAIL: PickDetail = {
  pick_id: 'pick-1',
  run_id: 'run-1',
  issued_at: '2026-06-01T08:50:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 3000,
  stop: 2800,
  target: 3300,
  sub_scores: { technical: 72, trend: 65, fundamental: 50, sentiment: 40 },
  composite_score: 72.5,
  concordance: 0.8,
  confidence_raw: 75,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_struct: { llm_risk_factors: ['金利上昇リスク'], holding_period_days: 10 },
  rationale_text: 'テクニカル・トレンドともに良好で強気の判断根拠が揃っている',
  model_version: 'v1',
  source_contributions: { technical: { weight_share: 0.6, contribution: 40, score: 70 } },
  created_at: '2026-06-01T08:50:01+09:00',
};

const PICK: PickSummary = {
  pick_id: 'pick-1',
  issued_at: '2026-06-01T08:50:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 3000,
  stop: 2800,
  target: 3300,
  composite_score: 72.5,
  concordance: 0.8,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_text: 'テクニカル・トレンドともに良好で強気の判断根拠が揃っている',
  model_version: 'v1',
  source_contributions: {},
};

describe('PicksBoard', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('ピックが無ければ空状態メッセージを出す', async () => {
    mockFetchPicks.mockResolvedValue([]);

    render(<PicksBoard />);

    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledWith('mid_term', { limit: 50 }));
    expect(await screen.findByText('本日のピックはまだありません')).toBeInTheDocument();
  });

  it('ピック一覧を確度順で表示する', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);

    render(<PicksBoard />);

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getByText('強気')).toBeInTheDocument();
    expect(screen.getByText('75（高）')).toBeInTheDocument();
  });

  it('タブ切り替えで系統別に再取得する', async () => {
    mockFetchPicks.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<PicksBoard />);
    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledWith('mid_term', { limit: 50 }));

    await user.click(screen.getByRole('button', { name: '短期' }));

    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledWith('short_term', { limit: 50 }));
  });

  it('手動更新ボタンでピック生成を実行し一覧を再取得する', async () => {
    mockFetchPicks.mockResolvedValue([]);
    mockRunPicks.mockResolvedValue({
      run_id: 'run-1',
      horizon_type: 'mid_term',
      issued_at: '2026-06-01T08:50:00+09:00',
      status: 'ok',
      picks: [PICK],
      rejected: [],
      message: null,
    });
    const user = userEvent.setup();

    render(<PicksBoard />);
    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: '手動更新' }));

    await waitFor(() => expect(mockRunPicks).toHaveBeenCalledWith('mid_term'));
    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledTimes(2));
  });

  it('LLM 未設定など ok 以外の status ではメッセージを表示する', async () => {
    mockFetchPicks.mockResolvedValue([]);
    mockRunPicks.mockResolvedValue({
      run_id: 'run-1',
      horizon_type: 'mid_term',
      issued_at: '2026-06-01T08:50:00+09:00',
      status: 'not_configured',
      picks: [],
      rejected: [],
      message: 'ANTHROPIC_API_KEY が未設定のためピックを生成できません',
    });
    const user = userEvent.setup();

    render(<PicksBoard />);
    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: '手動更新' }));

    expect(await screen.findByText('ANTHROPIC_API_KEY が未設定のためピックを生成できません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPicks.mockRejectedValue(new Error('boom'));

    render(<PicksBoard />);

    expect(await screen.findByText('ピック一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);

    const { container } = render(<PicksBoard />);
    await waitFor(() => expect(mockFetchPicks).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });

  it('銘柄名クリックでナレッジベースノートをポップアップ表示する', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);
    mockFetchStockNote.mockResolvedValue({ code: '7203', note_title: '7203_トヨタ自動車', content: 'ノート本文' });
    const user = userEvent.setup();

    render(<PicksBoard />);
    await user.click(await screen.findByText('7203（トヨタ自動車）'));

    expect(mockFetchStockNote).toHaveBeenCalledWith('7203');
    expect(await screen.findByText('ノート本文')).toBeInTheDocument();
    expect(screen.getByText('ナレッジベースノート: 7203')).toBeInTheDocument();
  });

  it('ノート未整備の銘柄では案内文を出す', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);
    mockFetchStockNote.mockResolvedValue(null);
    const user = userEvent.setup();

    render(<PicksBoard />);
    await user.click(await screen.findByText('7203（トヨタ自動車）'));

    expect(await screen.findByText('この銘柄のナレッジベースノートはまだありません')).toBeInTheDocument();
  });

  it('根拠「詳細」ボタンでピック詳細をポップアップ表示する', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);
    mockFetchPickDetail.mockResolvedValue(PICK_DETAIL);
    const user = userEvent.setup();

    render(<PicksBoard />);
    await user.click(await screen.findByRole('button', { name: '詳細' }));

    expect(mockFetchPickDetail).toHaveBeenCalledWith('pick-1');
    expect(await screen.findByText('テクニカル: 72')).toBeInTheDocument();
    expect(screen.getByText('金利上昇リスク')).toBeInTheDocument();
    expect(screen.getByText('想定保有期間: 約10営業日')).toBeInTheDocument();
  });

  it('ポップアップの閉じるボタンで閉じる', async () => {
    mockFetchPicks.mockResolvedValue([PICK]);
    mockFetchPickDetail.mockResolvedValue(PICK_DETAIL);
    const user = userEvent.setup();

    render(<PicksBoard />);
    await user.click(await screen.findByRole('button', { name: '詳細' }));
    await screen.findByText('ピック詳細・根拠');

    await user.click(screen.getByRole('button', { name: '閉じる' }));

    expect(screen.queryByText('ピック詳細・根拠')).not.toBeInTheDocument();
  });
});
