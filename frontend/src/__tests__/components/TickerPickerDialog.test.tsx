import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TickerPickerDialog } from '@/components/settings/TickerPickerDialog';
import { fetchTickerUniverse, updateTrainingTargetTickers } from '@/lib/api/registry';
import type { TickerUniverseEntry } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchUniverse = fetchTickerUniverse as jest.MockedFunction<typeof fetchTickerUniverse>;
const mockUpdateTickers = updateTrainingTargetTickers as jest.MockedFunction<typeof updateTrainingTargetTickers>;

const ENTRIES: TickerUniverseEntry[] = [
  { code: '1111', name: 'あいう銘柄', sector: 'サービス業', volume: 100, in_custom_list: false },
  { code: '2222', name: 'かきく銘柄', sector: '化学', volume: 900, in_custom_list: true },
];

describe('TickerPickerDialog', () => {
  beforeEach(() => {
    mockFetchUniverse.mockResolvedValue(ENTRIES);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄一覧を表示し、既存カスタムリストをチェック済みにする', async () => {
    render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);

    expect(await screen.findByText('1111')).toBeInTheDocument();
    const checkbox = await screen.findByRole('checkbox', { name: /2222/ });
    expect(checkbox).toBeChecked();
    expect(await screen.findByText('1 銘柄を選択中')).toBeInTheDocument();
  });

  it('チェックを切り替えると選択数が変わる', async () => {
    const user = userEvent.setup();
    render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);

    const checkbox = await screen.findByRole('checkbox', { name: /1111/ });
    await user.click(checkbox);

    expect(await screen.findByText('2 銘柄を選択中')).toBeInTheDocument();
  });

  it('保存すると選択集合を全置換で送信し、保存後にonSaved/onCloseを呼ぶ', async () => {
    const user = userEvent.setup();
    const onSaved = jest.fn();
    const onClose = jest.fn();
    mockUpdateTickers.mockResolvedValue([]);

    render(<TickerPickerDialog onClose={onClose} onSaved={onSaved} />);
    await screen.findByText('1111');

    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(mockUpdateTickers).toHaveBeenCalledWith(['2222']));
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('業種で絞り込むとAPIへ業種を渡す', async () => {
    const user = userEvent.setup();
    render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);
    await screen.findByText('1111');

    await user.selectOptions(screen.getByLabelText('業種'), '化学');

    await waitFor(() =>
      expect(mockFetchUniverse).toHaveBeenCalledWith({ sector: '化学', sort: 'code_asc', q: undefined }),
    );
  });

  it('検索語を入力するとデバウンス後にAPIへ渡す', async () => {
    const user = userEvent.setup();
    render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);
    await screen.findByText('1111');

    await user.type(screen.getByLabelText('検索'), '2222');

    await waitFor(
      () => expect(mockFetchUniverse).toHaveBeenCalledWith({ sector: undefined, sort: 'code_asc', q: '2222' }),
      { timeout: 2000 },
    );
  });

  it('出来高データが無ければ出来高ソートを無効化する通知を出す', async () => {
    mockFetchUniverse.mockResolvedValue(ENTRIES.map((e) => ({ ...e, volume: null })));
    render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);

    expect(await screen.findByText(/出来高ソートは無効になっています/)).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<TickerPickerDialog onClose={jest.fn()} onSaved={jest.fn()} />);
    await screen.findByText('1111');
    expect(await axe(container)).toHaveNoViolations();
  });
});
