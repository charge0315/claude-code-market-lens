import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PickDetailPanel } from '@/components/dashboard/PickDetailPanel';
import { fetchPickDetail } from '@/lib/api/picks';
import { fetchOhlc } from '@/lib/api/stock';
import type { PickDetail } from '@/lib/api/picks';

jest.mock('@/lib/api/picks');
jest.mock('@/lib/api/stock');

const mockFetchPickDetail = fetchPickDetail as jest.MockedFunction<typeof fetchPickDetail>;
const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

const BASE_DETAIL: PickDetail = {
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
  rationale_struct: {},
  rationale_text: 'テクニカル・トレンドともに良好で強気の判断根拠が揃っている',
  model_version: 'v1',
  source_contributions: {},
  created_at: '2026-06-01T08:50:01+09:00',
  shadow_predictions: [],
  current_price: null,
  change_pct: null,
};

describe('PickDetailPanel', () => {
  beforeEach(() => {
    mockFetchOhlc.mockResolvedValue({ bars: [], events: [] });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('読み込み中は案内文を出す', () => {
    mockFetchPickDetail.mockReturnValue(new Promise(() => undefined));
    render(<PickDetailPanel pickId="pick-1" />);
    expect(screen.getByText('読み込み中…')).toBeInTheDocument();
  });

  it('取得失敗時はエラーメッセージを出す', async () => {
    mockFetchPickDetail.mockRejectedValue(new Error('boom'));
    render(<PickDetailPanel pickId="pick-1" />);
    expect(await screen.findByText('ピック詳細の取得に失敗しました')).toBeInTheDocument();
  });

  it('見つからない場合は案内文を出す', async () => {
    // API 契約上は起こらない想定だが、コンポーネント側の防御的な null チェックを検証する。
    mockFetchPickDetail.mockResolvedValue(null as unknown as PickDetail);
    render(<PickDetailPanel pickId="pick-1" />);
    expect(await screen.findByText('詳細が見つかりません')).toBeInTheDocument();
  });

  it('current_price が null なら「—」と現在値比較無しで表示する', async () => {
    mockFetchPickDetail.mockResolvedValue(BASE_DETAIL);
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('ピックアップ根拠');
    expect(screen.getAllByText('—')).not.toHaveLength(0);
    // 現在値が無いため乖離率（例: +10.0%）は表示されない。
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it('current_price ありなら前日比・現在値乖離を表示する', async () => {
    mockFetchPickDetail.mockResolvedValue({ ...BASE_DETAIL, current_price: 3050, change_pct: -1.5 });
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('ピックアップ根拠');
    expect(screen.getByText('¥3,050')).toBeInTheDocument();
    expect(screen.getByText('-1.50%')).toBeInTheDocument();
    // entry=3000→-1.6%、stop=2800→-8.2%、target=3300→+8.2%（対 current_price=3050）
    expect(screen.getByText('-1.6%')).toBeInTheDocument();
    expect(screen.getByText('-8.2%')).toBeInTheDocument();
    expect(screen.getByText('+8.2%')).toBeInTheDocument();
  });

  it('source_contributions に該当カテゴリが無ければ寄与度は表示しない', async () => {
    mockFetchPickDetail.mockResolvedValue(BASE_DETAIL);
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('ピックアップ根拠');
    expect(screen.queryByText(/合成スコア寄与/)).not.toBeInTheDocument();
  });

  it('source_contributions に該当カテゴリがあれば合成スコア寄与を表示する', async () => {
    mockFetchPickDetail.mockResolvedValue({
      ...BASE_DETAIL,
      source_contributions: { technical: { weight_share: 0.6, contribution: 40, score: 70 } },
    });
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('ピックアップ根拠');
    expect(screen.getByText('合成スコア寄与 40.0（重み 60%）')).toBeInTheDocument();
  });

  it('留意点・想定保有期間があれば表示する', async () => {
    mockFetchPickDetail.mockResolvedValue({
      ...BASE_DETAIL,
      rationale_struct: { llm_risk_factors: ['金利上昇リスク'], holding_period_days: 10 },
    });
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('留意点');
    expect(screen.getByText('金利上昇リスク')).toBeInTheDocument();
    expect(screen.getByText('想定保有期間: 約10営業日')).toBeInTheDocument();
  });

  it('留意点・想定保有期間が無ければ表示しない', async () => {
    mockFetchPickDetail.mockResolvedValue(BASE_DETAIL);
    render(<PickDetailPanel pickId="pick-1" />);

    await screen.findByText('ピックアップ根拠');
    expect(screen.queryByText('留意点')).not.toBeInTheDocument();
    expect(screen.queryByText(/想定保有期間/)).not.toBeInTheDocument();
  });

  it('フッタにスコア・抽出日時・モデルバージョンを表示する', async () => {
    mockFetchPickDetail.mockResolvedValue(BASE_DETAIL);
    render(<PickDetailPanel pickId="pick-1" />);

    expect(await screen.findByText(/スコア 72.5/)).toBeInTheDocument();
    expect(screen.getByText(/モデルバージョン/)).toBeInTheDocument();
    expect(screen.getByText(/v1/)).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPickDetail.mockResolvedValue(BASE_DETAIL);
    const { container } = render(<PickDetailPanel pickId="pick-1" />);
    await screen.findByText('ピックアップ根拠');

    expect(await axe(container)).toHaveNoViolations();
  });
});
