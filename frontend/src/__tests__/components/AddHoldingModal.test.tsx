import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { AddHoldingModal } from '@/components/portfolio/AddHoldingModal';
import { addHolding } from '@/lib/api/portfolio';
import { fetchQuote } from '@/lib/api/stock';

jest.mock('@/lib/api/portfolio');
jest.mock('@/lib/api/stock');

const mockAddHolding = addHolding as jest.MockedFunction<typeof addHolding>;
const mockFetchQuote = fetchQuote as jest.MockedFunction<typeof fetchQuote>;

describe('AddHoldingModal', () => {
  beforeEach(() => {
    // 既定では最新値が取れない状況を再現し、suggestedPrice へのフォールバックを固定する。
    mockFetchQuote.mockRejectedValue(new Error('network error'));
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('推奨価格を取得単価の初期値として表示する', () => {
    render(<AddHoldingModal symbol="7203" companyName="トヨタ自動車" suggestedPrice={3000} onClose={jest.fn()} onAdded={jest.fn()} />);

    expect(screen.getByRole('heading', { name: 'ポートフォリオに追加: 7203（トヨタ自動車）' })).toBeInTheDocument();
    expect(screen.getByLabelText('取得単価（円）')).toHaveValue(3000);
  });

  it('最新値が取得できた場合はそれを取得単価の初期値として上書きする', async () => {
    mockFetchQuote.mockResolvedValue({ symbol: '7203', price: 3120, prev_close: 3100, change_pct: 0.65 });

    render(<AddHoldingModal symbol="7203" suggestedPrice={3000} onClose={jest.fn()} onAdded={jest.fn()} />);

    await waitFor(() => expect(screen.getByLabelText('取得単価（円）')).toHaveValue(3120));
    expect(screen.getByText(/現在値を初期値にしています/)).toBeInTheDocument();
  });

  it('入力内容でaddHoldingを呼び、成功したらonAdded・onCloseを呼ぶ', async () => {
    mockAddHolding.mockResolvedValue({ holding_id: 'h1' });
    const onAdded = jest.fn();
    const onClose = jest.fn();
    const user = userEvent.setup();

    render(<AddHoldingModal symbol="7203" onClose={onClose} onAdded={onAdded} />);

    await user.clear(screen.getByLabelText('株数'));
    await user.type(screen.getByLabelText('株数'), '50');
    await user.clear(screen.getByLabelText('取得単価（円）'));
    await user.type(screen.getByLabelText('取得単価（円）'), '2500');
    await user.click(screen.getByRole('button', { name: '追加する' }));

    expect(mockAddHolding).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: '7203', quantity: 50, avg_cost: 2500 }),
    );
    expect(onAdded).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('株数が0以下ならHTML5バリデーションで送信をブロックしaddHoldingを呼ばない', async () => {
    const user = userEvent.setup();
    render(<AddHoldingModal symbol="7203" suggestedPrice={1000} onClose={jest.fn()} onAdded={jest.fn()} />);

    const quantityInput = screen.getByLabelText('株数') as HTMLInputElement;
    await user.clear(quantityInput);
    await user.type(quantityInput, '0');
    await user.click(screen.getByRole('button', { name: '追加する' }));

    // min=1 の HTML5 制約により、ブラウザが submit イベント自体を発火させない
    // （本コンポーネントの JS バリデーションはこれをすり抜けた場合の保険）。
    expect(quantityInput.validity.valid).toBe(false);
    expect(mockAddHolding).not.toHaveBeenCalled();
  });

  it('追加失敗時はエラーメッセージを表示する', async () => {
    mockAddHolding.mockRejectedValue(new Error('conflict'));
    const user = userEvent.setup();

    render(<AddHoldingModal symbol="7203" suggestedPrice={1000} onClose={jest.fn()} onAdded={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: '追加する' }));

    expect(await screen.findByText(/追加に失敗しました/)).toBeInTheDocument();
  });

  it('キャンセルボタンでonCloseを呼ぶ', async () => {
    const onClose = jest.fn();
    const user = userEvent.setup();
    render(<AddHoldingModal symbol="7203" onClose={onClose} onAdded={jest.fn()} />);

    await user.click(screen.getByRole('button', { name: 'キャンセル' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<AddHoldingModal symbol="7203" suggestedPrice={1000} onClose={jest.fn()} onAdded={jest.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
