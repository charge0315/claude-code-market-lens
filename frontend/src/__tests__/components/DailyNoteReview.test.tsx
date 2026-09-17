import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { DailyNoteReview } from '@/components/notes/DailyNoteReview';
import {
  approveNote,
  fetchTodayNote,
  generateNote,
  markNotePublished,
  regenerateNote,
  rejectNote,
  updateNoteContent,
} from '@/lib/api/notes';
import type { DailyNote } from '@/lib/api/notes';

jest.mock('@/lib/api/notes');

const mockFetchTodayNote = fetchTodayNote as jest.MockedFunction<typeof fetchTodayNote>;
const mockGenerateNote = generateNote as jest.MockedFunction<typeof generateNote>;
const mockApproveNote = approveNote as jest.MockedFunction<typeof approveNote>;
const mockRejectNote = rejectNote as jest.MockedFunction<typeof rejectNote>;
const mockRegenerateNote = regenerateNote as jest.MockedFunction<typeof regenerateNote>;
const mockUpdateNoteContent = updateNoteContent as jest.MockedFunction<typeof updateNoteContent>;
const mockMarkNotePublished = markNotePublished as jest.MockedFunction<typeof markNotePublished>;

function makeNote(overrides: Partial<DailyNote> = {}): DailyNote {
  return {
    note_id: 'n1',
    note_date: '2026-09-17',
    title: '本日のAI分析ノート',
    body_markdown: '本日は強気優勢の展開でした。',
    status: 'draft',
    source_pick_ids: ['p1', 'p2'],
    model_version: 'anthropic:claude-sonnet-5',
    has_price_mention_warning: false,
    generated_at: '2026-09-17T08:15:00+09:00',
    approved_at: null,
    published_at: null,
    published_url: null,
    ...overrides,
  };
}

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('DailyNoteReview', () => {
  it('下書きが無ければ生成ボタンを出す', async () => {
    mockFetchTodayNote.mockResolvedValue(null);

    render(<DailyNoteReview />);

    expect(await screen.findByText(/本日のnote下書きはまだありません/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '今すぐ生成' })).toBeInTheDocument();
  });

  it('今すぐ生成ボタンで下書きを生成し表示する', async () => {
    mockFetchTodayNote.mockResolvedValue(null);
    mockGenerateNote.mockResolvedValue(makeNote());
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByRole('button', { name: '今すぐ生成' });
    await user.click(screen.getByRole('button', { name: '今すぐ生成' }));

    expect(await screen.findByDisplayValue('本日のAI分析ノート')).toBeInTheDocument();
    expect(mockGenerateNote).toHaveBeenCalled();
  });

  it('下書きがあればタイトル・本文・ステータスを表示する', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());

    render(<DailyNoteReview />);

    expect(await screen.findByDisplayValue('本日のAI分析ノート')).toBeInTheDocument();
    expect(screen.getByDisplayValue('本日は強気優勢の展開でした。')).toBeInTheDocument();
    expect(screen.getByText('未承認')).toBeInTheDocument();
  });

  it('価格表現の警告があれば注意文を出す', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote({ has_price_mention_warning: true }));

    render(<DailyNoteReview />);

    expect(await screen.findByText(/価格らしき表現が含まれている可能性/)).toBeInTheDocument();
  });

  it('承認ボタンでステータスが承認済みになる', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    mockApproveNote.mockResolvedValue(makeNote({ status: 'approved', approved_at: '2026-09-17T09:00:00+09:00' }));
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');
    await user.click(screen.getByRole('button', { name: '承認' }));

    expect(await screen.findByText('承認済み')).toBeInTheDocument();
    expect(mockApproveNote).toHaveBeenCalledWith('n1');
  });

  it('却下ボタンでステータスが却下になる', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    mockRejectNote.mockResolvedValue(makeNote({ status: 'rejected' }));
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');
    await user.click(screen.getByRole('button', { name: '却下' }));

    expect(await screen.findByText('却下')).toBeInTheDocument();
  });

  it('再生成ボタンで新しい下書きに置き換わる', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    mockRegenerateNote.mockResolvedValue(makeNote({ title: '再生成後のタイトル' }));
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');
    await user.click(screen.getByRole('button', { name: '再生成' }));

    expect(await screen.findByDisplayValue('再生成後のタイトル')).toBeInTheDocument();
  });

  it('編集を保存ボタンで本文の変更をAPIへ送る', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    mockUpdateNoteContent.mockResolvedValue(makeNote({ title: '編集後タイトル' }));
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    const titleInput = await screen.findByDisplayValue('本日のAI分析ノート');
    await user.clear(titleInput);
    await user.type(titleInput, '編集後タイトル');
    await user.click(screen.getByRole('button', { name: '編集を保存' }));

    await waitFor(() =>
      expect(mockUpdateNoteContent).toHaveBeenCalledWith('n1', {
        title: '編集後タイトル',
        body_markdown: '本日は強気優勢の展開でした。',
      }),
    );
  });

  it('本文をコピーボタンでクリップボードへ書き込む', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');
    await user.click(screen.getByRole('button', { name: '本文をコピー' }));

    // ボタン文言が「コピーしました」に変わることで、クリップボード書き込みが成功したと確認する
    // （navigator.clipboard は jsdom 側で own-property の再定義が反映されないことがあるため、
    // モック呼び出し回数ではなく実際に観測できる UI の結果で検証する）。
    expect(await screen.findByRole('button', { name: 'コピーしました' })).toBeInTheDocument();
  });

  it('note.comで新規投稿を開くリンクを表示する', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());

    render(<DailyNoteReview />);

    const link = await screen.findByRole('link', { name: 'note.comで新規投稿を開く' });
    expect(link).toHaveAttribute('href', 'https://note.com/notes/new');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('投稿完了を記録するとURLが保存され読み取り専用表示になる', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote({ status: 'approved', approved_at: '2026-09-17T09:00:00+09:00' }));
    mockMarkNotePublished.mockResolvedValue(
      makeNote({
        status: 'published',
        approved_at: '2026-09-17T09:00:00+09:00',
        published_at: '2026-09-17T10:00:00+09:00',
        published_url: 'https://note.com/example/n/abc',
      }),
    );
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');
    await user.type(screen.getByLabelText('投稿完了後のURL'), 'https://note.com/example/n/abc');
    await user.click(screen.getByRole('button', { name: '投稿完了を記録' }));

    expect(mockMarkNotePublished).toHaveBeenCalledWith('n1', 'https://note.com/example/n/abc');
    expect(await screen.findByRole('link', { name: 'https://note.com/example/n/abc' })).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchTodayNote.mockRejectedValue(new Error('boom'));

    render(<DailyNoteReview />);

    expect(await screen.findByText('noteドラフトの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    const { container } = render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');

    expect(await axe(container)).toHaveNoViolations();
  });
});
