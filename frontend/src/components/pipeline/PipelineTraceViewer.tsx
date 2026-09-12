'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchRecentRuns, type RunSummary } from '@/lib/api/inference';
import { deriveSnapshot } from '@/lib/pipeline/deriveSnapshot';
import { usePipelineTrace, type PipelineMode } from '@/lib/pipeline/usePipelineTrace';
import type { SourceContribution } from '@/lib/pipeline/types';
import { StageDag } from './StageDag';
import { ThinkingPanel } from './ThinkingPanel';
import { ShapBar } from './ShapBar';
import './pipeline.css';

// 銘柄詳細画面の「AI 推論トレース（ライブ / リプレイ）」セクション。実行一覧から選び、
// ライブ（SSE）/ リプレイ（保存イベント再生）を切り替えて DAG + Thinking + 寄与度バーを表示する。

function formatRunLabel(run: RunSummary): string {
  const time = run.started_at.slice(0, 16).replace('T', ' ');
  return `${run.symbol} / ${run.horizon_type} / ${time}（${run.status}）`;
}

function extractSourceContributions(
  events: readonly { stage: string; payload: Record<string, unknown> }[],
): Record<string, SourceContribution> {
  const synthesis = [...events].reverse().find((e) => e.stage === 'synthesis');
  const raw = synthesis?.payload.source_contributions;
  return raw && typeof raw === 'object' ? (raw as Record<string, SourceContribution>) : {};
}

export function PipelineTraceViewer({ symbol }: { symbol?: string | null } = {}): ReactNode {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [mode, setMode] = useState<PipelineMode>('live');
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // symbol 指定時はその銘柄の実行を優先的に見つけられるよう取得件数を広げる。
    fetchRecentRuns({ limit: symbol ? 100 : 10 })
      .then((data) => {
        if (cancelled) return;
        setRuns(data);
        const preferred = symbol ? data.find((r) => r.symbol === symbol) : undefined;
        setRunId((preferred ?? data[0])?.run_id ?? null);
      })
      .catch(() => {
        if (!cancelled) setLoadError('実行一覧の取得に失敗しました');
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const { events, error, isActive } = usePipelineTrace(runId, mode);
  const snapshot = runId ? deriveSnapshot(runId, events) : null;
  const sourceContributions = extractSourceContributions(events);

  return (
    <div className="pipeline-viewer">
      <div className="pipeline-viewer-toolbar">
        <label className="pipeline-run-picker">
          実行:
          <select
            value={runId ?? ''}
            onChange={(e) => setRunId(e.target.value || null)}
            disabled={runs.length === 0}
            aria-label="表示する推論実行"
          >
            {runs.length === 0 && <option value="">実行履歴がありません</option>}
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {formatRunLabel(run)}
              </option>
            ))}
          </select>
        </label>
        <div className="pipeline-mode-toggle" role="group" aria-label="表示モード">
          <button
            type="button"
            className={mode === 'live' ? 'is-active' : undefined}
            aria-pressed={mode === 'live'}
            onClick={() => setMode('live')}
          >
            ライブ
          </button>
          <button
            type="button"
            className={mode === 'replay' ? 'is-active' : undefined}
            aria-pressed={mode === 'replay'}
            onClick={() => setMode('replay')}
          >
            リプレイ
          </button>
        </div>
        {isActive && (
          <span className="pipeline-viewer-status" role="status">
            {mode === 'live' ? 'ライブ配信中…' : '再生中…'}
          </span>
        )}
      </div>

      {loadError && <p className="pipeline-viewer-error">{loadError}</p>}
      {error && <p className="pipeline-viewer-error">{error}</p>}

      {snapshot ? (
        <>
          <StageDag snapshot={snapshot} />
          <div className="pipeline-preview-grid">
            <ThinkingPanel events={events} />
            <ShapBar sourceContributions={sourceContributions} />
          </div>
        </>
      ) : (
        <p className="pipeline-viewer-empty">まだ推論実行がありません（ピック生成後に表示されます）</p>
      )}
    </div>
  );
}
