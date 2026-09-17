// 日次noteドラフト API（`backend/routers/notes.py`）の薄い型付きラッパ。
//
// note.com にはサードパーティ向けの公式投稿APIが無いため、投稿そのものは人間が手動で行う。
// このAPIは下書きの生成・編集・承認・却下・再生成と、投稿完了後のURL記録のみを担う。

import { api } from '@/lib/api/client';

export type NoteStatus = 'draft' | 'approved' | 'rejected' | 'published';

export interface DailyNote {
  note_id: string;
  note_date: string;
  title: string;
  body_markdown: string;
  status: NoteStatus;
  source_pick_ids: string[];
  model_version: string;
  has_price_mention_warning: boolean;
  generated_at: string;
  approved_at: string | null;
  published_at: string | null;
  published_url: string | null;
}

export function fetchTodayNote(): Promise<DailyNote | null> {
  return api.get<DailyNote | null>('/notes/today');
}

export function fetchRecentNotes(limit = 30): Promise<DailyNote[]> {
  return api.get<DailyNote[]>(`/notes?limit=${limit}`);
}

export function generateNote(options?: { force?: boolean }): Promise<DailyNote> {
  return api.post<DailyNote>(`/notes/generate${options?.force ? '?force=true' : ''}`);
}

export function updateNoteContent(noteId: string, payload: { title: string; body_markdown: string }): Promise<DailyNote> {
  return api.patch<DailyNote>(`/notes/${encodeURIComponent(noteId)}`, payload);
}

export function approveNote(noteId: string): Promise<DailyNote> {
  return api.post<DailyNote>(`/notes/${encodeURIComponent(noteId)}/approve`);
}

export function rejectNote(noteId: string): Promise<DailyNote> {
  return api.post<DailyNote>(`/notes/${encodeURIComponent(noteId)}/reject`);
}

export function regenerateNote(noteId: string): Promise<DailyNote> {
  return api.post<DailyNote>(`/notes/${encodeURIComponent(noteId)}/regenerate`);
}

export function markNotePublished(noteId: string, publishedUrl: string): Promise<DailyNote> {
  return api.post<DailyNote>(`/notes/${encodeURIComponent(noteId)}/mark-published`, { published_url: publishedUrl });
}
