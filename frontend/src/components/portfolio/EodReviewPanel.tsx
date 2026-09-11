'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchLatestEodReview, runEodReview, type EodReview } from '@/lib/api/portfolio';
import './portfolio.css';

// 大引け後レビュー（EOD Review）。通常は celery-beat が JST 16:31 に自動生成するが、
// 手動実行ボタンも用意する（既存があれば再利用、`force` は使わない — UI からの再生成は
// 意図しない上書きを避けるため一旦非対応）。

export function EodReviewPanel(): ReactNode {
  const [review, setReview] = useState<EodReview | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLatestEodReview()
      .then((r) => setReview(r))
      .catch(() => setError('大引け後レビューの取得に失敗しました'))
      .finally(() => setLoaded(true));
  }, []);

  const handleRun = (): void => {
    setRunning(true);
    setError(null);
    runEodReview()
      .then(setReview)
      .catch(() => setError('大引け後レビューの実行に失敗しました'))
      .finally(() => setRunning(false));
  };

  return (
    <div className="eod-review-panel">
      <div className="eod-review-header">
        <button type="button" onClick={handleRun} disabled={running}>
          {running ? '実行中…' : '本日分を実行'}
        </button>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {!loaded ? null : review === null ? (
        <p className="signal-queue-empty">レビューはまだ生成されていません</p>
      ) : (
        <div className="eod-review-body">
          <p className="eod-review-date">{review.review_date}</p>
          <p className="eod-review-summary">{review.summary}</p>
          {review.learned_heuristics.length > 0 && (
            <ul className="eod-review-heuristics">
              {review.learned_heuristics.map((h) => (
                <li key={h.heuristic}>
                  <span className="eod-review-heuristic-text">{h.heuristic}</span>
                  <span className="eod-review-heuristic-confidence">確信度 {(h.confidence * 100).toFixed(0)}%</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
