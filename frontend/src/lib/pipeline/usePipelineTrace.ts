'use client';

import { useEffect, useState } from 'react';
import { fetchReplay } from '@/lib/api/inference';
import { subscribeSse } from '@/lib/realtime/sse';
import type { TraceEvent } from './types';

export type PipelineMode = 'live' | 'replay';

// リプレイ再生の1ステップあたりの間隔（保存済みイベントを疑似的に進行させる）。
const REPLAY_STEP_MS = 600;

export interface UsePipelineTraceResult {
  events: TraceEvent[];
  error: string | null;
  isActive: boolean;
}

// stage_seq で upsert する（単純な追記ではなく）。SSE は毎接続 seq=0 から全イベントを
// 再配信するため、React Strict Mode の dev 専用 effect 二重実行（旧 EventSource が close()
// される前に届いたメッセージ）や、意図しない再接続があっても重複を作らない。
function upsertByStageSeq(prev: readonly TraceEvent[], incoming: TraceEvent): TraceEvent[] {
  const idx = prev.findIndex((e) => e.stage_seq === incoming.stage_seq);
  if (idx === -1) {
    return [...prev, incoming].sort((a, b) => a.stage_seq - b.stage_seq);
  }
  const next = [...prev];
  next[idx] = incoming;
  return next;
}

// live: SSE で新規イベントをそのまま反映する（既に完了した run も接続直後に全イベントを
// 受け取ってから "done" で終わる — サーバ側が毎接続 seq=0 から配信するため）。
// replay: 保存済みイベントを一括取得し、一定間隔で1件ずつ出して進行を再現する。
export function usePipelineTrace(runId: string | null, mode: PipelineMode): UsePipelineTraceResult {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  // isDone は非同期コールバック（SSE イベント / Promise / タイマー）からのみ true にする
  // （effect 本体の同期 setState は React の推奨に反するため避ける）。isActive はここから導出する。
  const [isDone, setIsDone] = useState(false);

  // runId/mode が変わったら events/error/isDone をリセットする。effect 内での無条件な同期
  // setState は避け、React 公式の「レンダー中に前回値と比較して直ちに setState する」パターンを
  // 使う（https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes）。
  const trackKey = `${runId ?? ''}:${mode}`;
  const [prevTrackKey, setPrevTrackKey] = useState(trackKey);
  if (trackKey !== prevTrackKey) {
    setPrevTrackKey(trackKey);
    setEvents([]);
    setError(null);
    setIsDone(false);
  }

  useEffect(() => {
    if (!runId) return undefined;

    if (mode === 'live') {
      // ブラウザ標準の EventSource はサーバがストリームを終えても既定で自動再接続する
      // （SSE 仕様上、切断は「エラー」と「意図的な終了」を区別しない）。"done"/"timeout" を
      // 受け取ったら明示的に close() して再接続を止め、close 後に発火し得る onerror は
      // 無害な後始末として無視する（closed フラグで判定）。
      let closed = false;
      const subscription = subscribeSse(`/api/inference/${encodeURIComponent(runId)}/stream`, {
        onMessage: (data) => setEvents((prev) => upsertByStageSeq(prev, data as TraceEvent)),
        onNamed: {
          done: () => {
            closed = true;
            subscription.close();
            setIsDone(true);
          },
          timeout: () => {
            closed = true;
            subscription.close();
            setIsDone(true);
          },
        },
        onError: () => {
          if (closed) return;
          closed = true;
          subscription.close();
          setError('ライブ配信への接続に失敗しました');
          setIsDone(true);
        },
      });
      return () => {
        closed = true;
        subscription.close();
      };
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    fetchReplay(runId)
      .then((all) => {
        if (cancelled) return;
        let i = 0;
        const step = (): void => {
          if (cancelled) return;
          if (i >= all.length) {
            setIsDone(true);
            return;
          }
          // updater クロージャの実行タイミングは React に委ねられ、i の同期インクリメントより
          // 後に呼ばれることがある（クロージャが可変な外側変数 i を読むと値がずれる）。
          // setEvents に渡す前に値を確定させておく。
          const nextEvent = all[i];
          i += 1;
          setEvents((prev) => upsertByStageSeq(prev, nextEvent));
          timer = setTimeout(step, REPLAY_STEP_MS);
        };
        step();
      })
      .catch(() => {
        if (!cancelled) {
          setError('リプレイの取得に失敗しました');
          setIsDone(true);
        }
      });
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId, mode]);

  return { events, error, isActive: runId !== null && !isDone };
}
