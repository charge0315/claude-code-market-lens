import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TrainingTriggerPanel } from '@/components/model-lab/TrainingTriggerPanel';
import { fetchModelCoverage, fetchTrainingStatus, startTrainingBatch } from '@/lib/api/registry';
import type {
  ModelCoverage,
  TrainingBatchSummary,
  TrainingModelType,
  TrainingRunAck,
  TrainingStatus,
} from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockStart = startTrainingBatch as jest.MockedFunction<typeof startTrainingBatch>;
const mockStatus = fetchTrainingStatus as jest.MockedFunction<typeof fetchTrainingStatus>;
const mockCoverage = fetchModelCoverage as jest.MockedFunction<typeof fetchModelCoverage>;

const SUMMARY: TrainingBatchSummary = {
  model_type: 'xgboost',
  attempted_today: 5,
  trained_this_call: 3,
  failed_this_call: 0,
  quota_reached: false,
  activated_this_call: 2,
  error: null,
};

const IDLE_STATUS: TrainingStatus = {
  model_type: 'xgboost',
  running: false,
  attempted_today: 5,
  last_result: SUMMARY,
  progress: null,
};

const COVERAGE: ModelCoverage[] = (['xgboost', 'random_forest', 'lstm', 'transformer'] as TrainingModelType[]).map(
  (model_type) => ({
    model_type,
    label: model_type,
    universe_size: 4000,
    trained_count: 2000,
    champion_count: 500,
    yfinance_count: 1800,
    jquants_count: 200,
    last_trained_at: '2026-09-12T06:00:00+09:00',
  }),
);

// 🔧 P24: ボタンはモデルごとにカード内へ配置されているため、カードの見出し（例: "XGBoost"）
// を起点にそのカード内の「学習を開始」ボタンだけを取得する。
function startButtonFor(modelLabel: string): HTMLElement {
  const heading = screen.getByText(modelLabel);
  const card = heading.closest('li');
  if (!card) throw new Error(`カードが見つかりません: ${modelLabel}`);
  return within(card).getByRole('button', { name: /学習を開始|実行中/ });
}

describe('TrainingTriggerPanel', () => {
  beforeEach(() => {
    mockCoverage.mockResolvedValue(COVERAGE);
  });

  afterEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
  });

  it('🆕 P14: モデルタイプごとに平易な説明と既定設定を表示する', async () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText(/表形式データの学習が得意な高速AI/)).toBeInTheDocument();
    expect(screen.getByText('既定設定: 決定木100本・木の深さ5・学習率0.1')).toBeInTheDocument();
    await waitFor(() => expect(mockCoverage).toHaveBeenCalled());
  });

  it('4モデルタイプ名とタグラインを表示する', () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText('XGBoost')).toBeInTheDocument();
    expect(screen.getByText('勾配ブースティング木')).toBeInTheDocument();
    expect(screen.getByText('RandomForest')).toBeInTheDocument();
    expect(screen.getByText('LSTM')).toBeInTheDocument();
    expect(screen.getByText('Transformer')).toBeInTheDocument();
  });

  it('🔧 P24: モデルごとのボタンでそのモデルだけを起動する', async () => {
    mockStart.mockResolvedValue({ model_type: 'xgboost', status: 'started' } as TrainingRunAck);
    mockStatus.mockResolvedValue(IDLE_STATUS);
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(startButtonFor('XGBoost'));

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    expect(mockStart).toHaveBeenCalledWith('xgboost');
  });

  it('4枚のカードにそれぞれ独立した「学習を開始」ボタンがある', () => {
    render(<TrainingTriggerPanel />);

    ['XGBoost', 'RandomForest', 'LSTM', 'Transformer'].forEach((label) => {
      expect(startButtonFor(label)).toBeInTheDocument();
    });
  });

  it('実行中は処理中の銘柄・進捗率・残り推定時間・既存比をライブ表示する', async () => {
    mockStart.mockResolvedValue({ model_type: 'xgboost', status: 'started' } as TrainingRunAck);
    mockStatus.mockImplementation(async (modelType) => ({
      model_type: modelType,
      running: modelType === 'xgboost',
      attempted_today: 100,
      last_result: null,
      progress:
        modelType === 'xgboost'
          ? {
              current_ticker: '7203',
              processed: 10,
              total: 40,
              failed_this_run: 1,
              eta_seconds: 5400,
              promotion_rate_pct: 80,
            }
          : null,
    }));
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(startButtonFor('XGBoost'));

    expect(await screen.findByText('7203')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument(); // 10/40
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('1時間30分')).toBeInTheDocument();
    expect(screen.getByText('1件')).toBeInTheDocument();
    expect(screen.getByText(/実行中 1\/4 モデル/)).toBeInTheDocument();
  });

  it('学習結果がエラーを含む場合は実行ログにエラーを表示する', async () => {
    mockStart.mockResolvedValue({ model_type: 'xgboost', status: 'started' } as TrainingRunAck);
    mockStatus.mockImplementation(async (modelType) => ({
      model_type: modelType,
      running: false,
      attempted_today: 0,
      last_result:
        modelType === 'xgboost' ? { ...SUMMARY, error: 'unexpected failure' } : { ...SUMMARY, model_type: modelType },
      progress: null,
    }));
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(startButtonFor('XGBoost'));

    expect(await screen.findByText(/前回の実行でエラーが発生しました（unexpected failure）/)).toBeInTheDocument();
  });

  it('起動リクエスト自体が失敗した場合はそのモデルのエラーメッセージを表示する', async () => {
    mockStart.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(startButtonFor('XGBoost'));

    expect(await screen.findAllByText('学習の起動に失敗しました')).toHaveLength(1);
  });

  it('データソース内訳（yfinance/J-Quants）と最終学習日時を表示する', async () => {
    render(<TrainingTriggerPanel />);

    await waitFor(() => expect(mockCoverage).toHaveBeenCalled());
    expect(await screen.findAllByText(/yfinance 45%/)).not.toHaveLength(0); // 1800/4000
    expect(await screen.findAllByText(/J-Quants補完 5%/)).not.toHaveLength(0); // 200/4000
  });

  it('実行履歴が無ければ案内文を出す', () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText('まだ実行履歴がありません。上の各モデルのボタンから学習を開始してください。')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<TrainingTriggerPanel />);
    await waitFor(() => expect(mockCoverage).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
