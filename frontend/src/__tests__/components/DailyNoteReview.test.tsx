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
import { fetchPicks } from '@/lib/api/picks';
import type { PickSummary } from '@/lib/api/picks';

jest.mock('@/lib/api/notes');
jest.mock('@/lib/api/picks');

const mockFetchTodayNote = fetchTodayNote as jest.MockedFunction<typeof fetchTodayNote>;
const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
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
  mockFetchPicks.mockResolvedValue([]);
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

  it('下書きがあればタイトル・本文（note.comプレビュー）・ステータスを表示する', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());

    render(<DailyNoteReview />);

    expect(await screen.findByDisplayValue('本日のAI分析ノート')).toBeInTheDocument();
    // 既定はプレビュー表示（note.comへ貼り付けたときの見た目）で、生のMarkdownテキストボックスは出さない。
    expect(screen.getByText('本日は強気優勢の展開でした。')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('本日は強気優勢の展開でした。')).not.toBeInTheDocument();
    expect(screen.getByText('未承認')).toBeInTheDocument();
  });

  it('プレビューはMarkdown記法を変換して表示し、Markdown編集タブで生のテキストを編集できる', async () => {
    mockFetchTodayNote.mockResolvedValue(
      makeNote({ body_markdown: '## 見出し\n\n**強調**テキストです。' }),
    );
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');

    // 既定のプレビューでは "##"/"**" が文字として見えず、見出し要素・強調要素へ変換される。
    expect(screen.getByRole('heading', { level: 2, name: '見出し' })).toBeInTheDocument();
    expect(screen.queryByText(/##\s*見出し/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\*\*強調\*\*/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Markdown編集' }));

    expect(screen.getByLabelText('本文（Markdown）')).toHaveValue('## 見出し\n\n**強調**テキストです。');
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

  it('参考ピックがある場合も本文をコピーボタンが正常に完了する（note.comチャートトリガー挿入込み）', async () => {
    // トリガー挿入自体のロジックは `lib/noteComChartTriggers.test.ts` で純粋関数として検証済み。
    // ここでは sourcePicks の配線（symbol抽出→copyNoteToClipboardへの受け渡し）がコピー成功を
    // 妨げないことを、他のコピーテストと同じくUI観測可能な結果（ボタン文言）で確認する
    // （navigator.clipboard の再定義はモック呼び出し内容の検証には使えないため — 既知の制約）。
    mockFetchTodayNote.mockResolvedValue(
      makeNote({
        source_pick_ids: ['p1'],
        body_markdown: '解説です。\n\n### 7203（トヨタ自動車）中長期・強気\n\n強気の展開です。',
      }),
    );
    const matching: PickSummary = {
      pick_id: 'p1',
      issued_at: '2026-09-17T08:50:00+09:00',
      horizon_type: 'mid_term',
      symbol: '7203',
      company_name: 'トヨタ自動車',
      direction: 'bullish',
      entry: 1000,
      stop: 950,
      target: 1100,
      composite_score: 60,
      concordance: 0.8,
      confidence: 70,
      confidence_bucket: 'high',
      rationale_text: 'x',
      model_version: 'v1',
      source_contributions: {},
      current_price: null,
      change_pct: null,
      spark: [100, 110, 105],
      reasoning_tags: [],
    };
    mockFetchPicks.mockImplementation((horizonType) =>
      Promise.resolve(horizonType === 'mid_term' ? [matching] : []),
    );
    const user = userEvent.setup();

    render(<DailyNoteReview />);
    await screen.findByRole('img', { name: /7203（トヨタ自動車）/ });
    await user.click(screen.getByRole('button', { name: '本文をコピー' }));

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

  it('source_pick_idsに一致するピックのみ参考チャートとして表示する', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote({ source_pick_ids: ['p1'] }));
    const matching: PickSummary = {
      pick_id: 'p1',
      issued_at: '2026-09-17T08:50:00+09:00',
      horizon_type: 'mid_term',
      symbol: '7203',
      company_name: 'トヨタ自動車',
      direction: 'bullish',
      entry: 1000,
      stop: 950,
      target: 1100,
      composite_score: 60,
      concordance: 0.8,
      confidence: 70,
      confidence_bucket: 'high',
      rationale_text: 'x',
      model_version: 'v1',
      source_contributions: {},
      current_price: null,
      change_pct: null,
      spark: [100, 110, 105],
      reasoning_tags: [],
    };
    const unrelated: PickSummary = { ...matching, pick_id: 'p2', symbol: '9984' };
    mockFetchPicks.mockImplementation((horizonType) =>
      Promise.resolve(horizonType === 'mid_term' ? [matching, unrelated] : []),
    );

    render(<DailyNoteReview />);

    expect(await screen.findByRole('img', { name: /7203（トヨタ自動車）/ })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /9984/ })).not.toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchTodayNote.mockResolvedValue(makeNote());
    const { container } = render(<DailyNoteReview />);
    await screen.findByDisplayValue('本日のAI分析ノート');

    expect(await axe(container)).toHaveNoViolations();
  });
});
