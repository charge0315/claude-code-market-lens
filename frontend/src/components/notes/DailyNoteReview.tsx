'use client';

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import {
  approveNote,
  fetchTodayNote,
  generateNote,
  markNotePublished,
  regenerateNote,
  rejectNote,
  updateNoteContent,
  type DailyNote,
} from '@/lib/api/notes';
import { escapeHtml, markdownToHtml } from '@/lib/markdownToHtml';
import { fetchPicks, type PickSummary } from '@/lib/api/picks';
import { NoteChartCard } from './NoteChartCard';
import './notes.css';

// 日次noteドラフトのレビューカード（🆕）。celery-beat が JST 08:15 に自動生成した本日の
// 下書きを確認・編集し、承認/却下する。note.com には公式投稿APIが無いため、投稿そのものは
// 「本文をコピー→note.comで新規投稿を開く→手動で貼り付け」という人間の操作に委ね、
// 投稿後はURLをこの画面で記録するだけ（半自動、CLAUDE.mdの承認制パターンを踏襲）。

const STATUS_LABELS: Record<DailyNote['status'], string> = {
  draft: '未承認',
  approved: '承認済み',
  rejected: '却下',
  published: '投稿済み',
};

const NOTE_COM_NEW_POST_URL = 'https://note.com/notes/new';

// note.com のエディタはリッチテキストのため、プレーンテキストの Markdown 記法（##, ** 等）を
// そのまま貼り付けても見出し・太字にならない（実機確認済み）。text/html も添えてコピーし、
// 対応先のリッチペーストで書式が反映されるようにする。ClipboardItem 非対応環境（jsdom 等）では
// プレーンテキストのみへフォールバックする。
function copyNoteToClipboard(title: string, bodyMarkdown: string): Promise<void> {
  const plain = `${title}\n\n${bodyMarkdown}`;
  if (typeof ClipboardItem === 'undefined' || !navigator.clipboard.write) {
    return navigator.clipboard.writeText(plain);
  }
  const html = `<h1>${escapeHtml(title)}</h1>\n${markdownToHtml(bodyMarkdown)}`;
  const item = new ClipboardItem({
    'text/plain': new Blob([plain], { type: 'text/plain' }),
    'text/html': new Blob([html], { type: 'text/html' }),
  });
  return navigator.clipboard.write([item]);
}

export function DailyNoteReview(): ReactNode {
  const [note, setNote] = useState<DailyNote | null | undefined>(undefined);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [publishedUrlInput, setPublishedUrlInput] = useState('');
  const [sourcePicks, setSourcePicks] = useState<PickSummary[]>([]);

  const load = useCallback(() => {
    fetchTodayNote()
      .then((n) => {
        setNote(n);
        if (n) {
          setTitle(n.title);
          setBody(n.body_markdown);
        }
      })
      .catch(() => {
        setError('noteドラフトの取得に失敗しました');
        setNote(null);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // チャート素材（値動き）を取得する。source_pick_ids には entry/stop/target を含まない
  // PickSummary（spark配列のみ利用）を突き合わせるだけで、3値は一切扱わない。
  useEffect(() => {
    // source_pick_ids が空（その日ピックが1件も無かった等）なら、初期値の空配列のまま
    // で問題ない（`note_id` は日付ごとに安定しており、再生成しても picks は変わらないため、
    // 「populated→emptyへ戻す」再設定が必要になる実用上のケースは無い）。
    if (!note || note.source_pick_ids.length === 0) {
      return;
    }
    const ids = new Set(note.source_pick_ids);
    Promise.all([
      fetchPicks('mid_term', { date: note.note_date, limit: 50 }),
      fetchPicks('short_term', { date: note.note_date, limit: 50 }),
    ])
      .then(([mid, short]) => setSourcePicks([...mid, ...short].filter((p) => ids.has(p.pick_id))))
      .catch(() => setSourcePicks([]));
  }, [note]);

  const applyResult = (updated: DailyNote): void => {
    setNote(updated);
    setTitle(updated.title);
    setBody(updated.body_markdown);
  };

  const handleGenerate = (): void => {
    setBusy(true);
    setError(null);
    generateNote()
      .then(applyResult)
      .catch(() => setError('生成に失敗しました'))
      .finally(() => setBusy(false));
  };

  const handleSaveEdit = (): void => {
    if (!note) return;
    setBusy(true);
    setError(null);
    updateNoteContent(note.note_id, { title, body_markdown: body })
      .then(applyResult)
      .catch(() => setError('保存に失敗しました'))
      .finally(() => setBusy(false));
  };

  const handleApprove = (): void => {
    if (!note) return;
    setBusy(true);
    setError(null);
    approveNote(note.note_id)
      .then(applyResult)
      .catch(() => setError('承認に失敗しました'))
      .finally(() => setBusy(false));
  };

  const handleReject = (): void => {
    if (!note) return;
    setBusy(true);
    setError(null);
    rejectNote(note.note_id)
      .then(applyResult)
      .catch(() => setError('却下に失敗しました'))
      .finally(() => setBusy(false));
  };

  const handleRegenerate = (): void => {
    if (!note) return;
    setBusy(true);
    setError(null);
    regenerateNote(note.note_id)
      .then(applyResult)
      .catch(() => setError('再生成に失敗しました'))
      .finally(() => setBusy(false));
  };

  const handleCopy = (): void => {
    copyNoteToClipboard(title, body)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 3000);
      })
      .catch(() => setError('コピーに失敗しました（ブラウザの権限設定をご確認ください）'));
  };

  const handleMarkPublished = (e: FormEvent): void => {
    e.preventDefault();
    if (!note || !publishedUrlInput.trim()) return;
    setBusy(true);
    setError(null);
    markNotePublished(note.note_id, publishedUrlInput.trim())
      .then((updated) => {
        applyResult(updated);
        setPublishedUrlInput('');
      })
      .catch(() => setError('投稿完了の記録に失敗しました'))
      .finally(() => setBusy(false));
  };

  if (note === undefined) {
    return null;
  }

  if (note === null) {
    return (
      <div className="daily-note-review">
        <p className="signal-queue-empty">本日のnote下書きはまだありません（08:15頃に自動生成されます）</p>
        {error && <p className="signal-queue-error">{error}</p>}
        <button type="button" onClick={handleGenerate} disabled={busy}>
          {busy ? '生成中…' : '今すぐ生成'}
        </button>
      </div>
    );
  }

  return (
    <div className="daily-note-review">
      <div className="daily-note-review-header">
        <span className={`daily-note-status daily-note-status--${note.status}`}>{STATUS_LABELS[note.status]}</span>
        <span className="daily-note-meta">
          {note.note_date} / {note.model_version}
        </span>
      </div>

      {note.has_price_mention_warning && (
        <p className="daily-note-warning">
          ⚠ 本文に価格らしき表現が含まれている可能性があります。投稿前に必ず内容をご確認ください。
        </p>
      )}

      {error && <p className="signal-queue-error">{error}</p>}

      <label className="daily-note-field">
        タイトル
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} disabled={note.status === 'published'} />
      </label>
      <label className="daily-note-field">
        本文（Markdown）
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={14}
          disabled={note.status === 'published'}
        />
      </label>

      {sourcePicks.length > 0 && (
        <div className="daily-note-charts">
          <p className="daily-note-charts-label">
            参考チャート（記事へ挿入する場合は画像として保存し、note.comへ手動アップロードしてください）
          </p>
          <div className="daily-note-charts-grid">
            {sourcePicks.map((p) => (
              <NoteChartCard key={p.pick_id} symbol={p.symbol} companyName={p.company_name} values={p.spark} />
            ))}
          </div>
        </div>
      )}

      {note.status !== 'published' && (
        <div className="daily-note-actions">
          <button type="button" onClick={handleSaveEdit} disabled={busy}>
            編集を保存
          </button>
          {note.status === 'draft' && (
            <button type="button" onClick={handleApprove} disabled={busy}>
              承認
            </button>
          )}
          {note.status !== 'rejected' && (
            <button type="button" onClick={handleReject} disabled={busy}>
              却下
            </button>
          )}
          <button type="button" onClick={handleRegenerate} disabled={busy}>
            再生成
          </button>
        </div>
      )}

      {(note.status === 'approved' || note.status === 'draft') && (
        <div className="daily-note-publish">
          <div className="daily-note-actions">
            <button type="button" onClick={handleCopy}>
              {copied ? 'コピーしました' : '本文をコピー'}
            </button>
            <a href={NOTE_COM_NEW_POST_URL} target="_blank" rel="noreferrer">
              note.comで新規投稿を開く
            </a>
          </div>
          <form className="daily-note-publish-form" onSubmit={handleMarkPublished}>
            <label>
              投稿完了後のURL
              <input
                type="url"
                value={publishedUrlInput}
                onChange={(e) => setPublishedUrlInput(e.target.value)}
                placeholder="https://note.com/..."
              />
            </label>
            <button type="submit" disabled={busy || !publishedUrlInput.trim()}>
              投稿完了を記録
            </button>
          </form>
        </div>
      )}

      {note.status === 'published' && note.published_url && (
        <p className="daily-note-published-link">
          投稿済み:{' '}
          <a href={note.published_url} target="_blank" rel="noreferrer">
            {note.published_url}
          </a>
        </p>
      )}
    </div>
  );
}
