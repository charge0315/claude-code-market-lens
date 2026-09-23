'use client';

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError } from '@/lib/api/client';
import {
  fetchReplayDetail,
  fetchReplayRuns,
  resumeReplay,
  startReplay,
  stopReplay,
  type ReplayDetail,
  type ReplayRun,
  type ReplayStatus,
} from '@/lib/api/replay';
import { LivePerformanceTable, SummaryTables } from '@/components/model-lab/ReplayResults';
import './model-lab.css';
import './replay.css';

// 過去日リプレイ学習（🆕 P37）の操作パネル。取得できる最古の日から 1 営業日ずつ、
// その日の大引け時点の情報だけで AI ピック（LLM なしの定量部分）を再現し、翌日以降の
// 実データで答え合わせして学習材料にする。実行は backend の別プロセスで進むため、
// 実行中は一定間隔で進捗を取り直す。

const POLL_INTERVAL_MS = 10_000;
const ACTIVE_STATUSES: ReadonlySet<ReplayStatus> = new Set<ReplayStatus>(['pending', 'running', 'stopping']);

const STATUS_LABELS: Record<ReplayStatus, string> = {
  pending: '起動中',
  running: '実行中',
  stopping: '停止処理中',
  stopped: '停止',
  completed: '完了',
  failed: '失敗',
};

function progressPercent(run: ReplayRun): number {
  const start = Date.parse(run.start_date);
  const span = Date.parse(run.end_date) - start;
  if (!run.cursor_date || span <= 0) return 0;
  return Math.min(100, Math.max(0, Math.floor(((Date.parse(run.cursor_date) - start) / span) * 100)));
}

interface Snapshot {
  latest: ReplayRun | null;
  detail: ReplayDetail | null;
}

// state に触れない取得処理。反映は呼び出し側の then で行う（エフェクト内で同期的に setState しない）。
async function fetchSnapshot(): Promise<Snapshot> {
  const runs = await fetchReplayRuns();
  const latest = runs[0] ?? null;
  return {
    latest,
    detail: latest ? await fetchReplayDetail(latest.run_id) : null,
  };
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function StartForm({
  onStart,
  busy,
}: {
  onStart: (range: { start_date?: string; end_date?: string }) => void;
  busy: boolean;
}): ReactNode {
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    onStart({
      ...(startDate ? { start_date: startDate } : {}),
      ...(endDate ? { end_date: endDate } : {}),
    });
  };

  return (
    <form className="replay-form" onSubmit={submit}>
      <label className="replay-field">
        <span>開始日</span>
        <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
      </label>
      <label className="replay-field">
        <span>終了日</span>
        <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
      </label>
      <button type="submit" className="replay-primary" disabled={busy}>
        リプレイを開始
      </button>
      <p className="model-lab-as-of replay-form-note">
        省略時は昨日までの直近4年（その前の1年は指標の助走に使います）。全期間で数十分〜数時間かかります。
      </p>
    </form>
  );
}

function RunStatus({ detail }: { detail: ReplayDetail }): ReactNode {
  const { run } = detail;
  const pct = progressPercent(run);
  const lastAuc = detail.retrains.at(-1)?.metrics.auc;
  const picks = (detail.pick_counts.short_term ?? 0) + (detail.pick_counts.mid_term ?? 0);
  return (
    <div className="replay-status">
      <div className="replay-status-row">
        <span className={run.is_alive ? 'ml-tag ml-tag-accent' : 'ml-tag ml-tag-neutral'}>
          {STATUS_LABELS[run.status]}
        </span>
        <span className="num">
          {run.start_date} → {run.cursor_date ?? '—'} / {run.end_date}
        </span>
      </div>
      <div
        className="replay-progress"
        role="progressbar"
        aria-label="リプレイの進み具合"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className="replay-progress-fill" style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
      <p className="model-lab-as-of">
        再現したピック {picks.toLocaleString('ja-JP')} 件・モデル再学習 {detail.retrains.length} 回
        {typeof lastAuc === 'number' ? `（直近の検証 AUC ${lastAuc.toFixed(3)}）` : ''}
      </p>
      {run.error ? (
        <p className="replay-error" role="alert">
          {run.error}
        </p>
      ) : null}
    </div>
  );
}

export function ReplayPanel(): ReactNode {
  const [latest, setLatest] = useState<ReplayRun | null>(null);
  const [detail, setDetail] = useState<ReplayDetail | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((): Promise<void> => {
    return fetchSnapshot()
      .then((snap) => {
        setLatest(snap.latest);
        setDetail(snap.detail);
      })
      .catch((err: unknown) => setError(messageOf(err, 'リプレイの状況を取得できませんでした')))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchSnapshot()
      .then((snap) => {
        if (cancelled) return;
        setLatest(snap.latest);
        setDetail(snap.detail);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(messageOf(err, 'リプレイの状況を取得できませんでした'));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const alive = latest?.is_alive ?? false;
  useEffect(() => {
    if (!alive) return undefined;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [alive, load]);

  const act = (action: () => Promise<unknown>, fallback: string): void => {
    setBusy(true);
    setError(null);
    action()
      .then(() => load())
      .catch((err: unknown) => setError(messageOf(err, fallback)))
      .finally(() => setBusy(false));
  };

  if (!loaded) return <p className="model-lab-as-of">読み込み中…</p>;

  // 停止・失敗に加え、プロセスが落ちてハートビートが途絶えた実行（status は running のまま）も再開できる。
  const canResume = latest !== null && !alive && latest.status !== 'completed';
  const isStale = latest !== null && !alive && ACTIVE_STATUSES.has(latest.status);

  return (
    <div className="replay-panel">
      {error ? (
        <p className="replay-error" role="alert">
          {error}
        </p>
      ) : null}

      {detail ? <RunStatus detail={detail} /> : null}

      <div className="replay-actions">
        {alive && latest ? (
          <button
            type="button"
            onClick={() => act(() => stopReplay(latest.run_id), '停止できませんでした')}
            disabled={busy || latest.status === 'stopping'}
          >
            停止
          </button>
        ) : null}
        {canResume && latest ? (
          <button
            type="button"
            className="replay-primary"
            onClick={() => act(() => resumeReplay(latest.run_id), '再開できませんでした')}
            disabled={busy}
          >
            続きから再開
          </button>
        ) : null}
      </div>

      {!alive ? (
        <StartForm busy={busy} onStart={(range) => act(() => startReplay(range), '開始できませんでした')} />
      ) : null}
      {isStale ? (
        <p className="model-lab-as-of">前回の実行は応答が途絶えています。「続きから再開」で再開できます。</p>
      ) : null}

      {detail ? (
        <>
          <h3 className="replay-subheading">答え合わせの途中成績</h3>
          <LivePerformanceTable detail={detail} />
        </>
      ) : null}
      {detail?.run.summary ? <SummaryTables summary={detail.run.summary} /> : null}
    </div>
  );
}
