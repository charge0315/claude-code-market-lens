'use client';

import { useRef, useState, type ReactNode } from 'react';
import { downloadSvgAsPng } from '@/lib/exportChartImage';
import { NoteChart } from './NoteChart';

// チャート1件分 + 「画像として保存」ボタン（🆕）。note.comには画像アップロードの公式APIが
// 無く、text/htmlクリップボードへの埋め込みも確実ではないため、PNGとして個別にダウンロードし、
// 記事本文の該当箇所へ手動で挿入してもらう設計にする（本文コピーと同じ半自動方針）。

export function NoteChartCard({ symbol, companyName, values }: { symbol: string; companyName: string | null; values: readonly number[] }): ReactNode {
  const svgRef = useRef<SVGSVGElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const title = companyName ? `${symbol}（${companyName}）` : symbol;

  const handleSave = (): void => {
    setError(null);
    if (!svgRef.current) return;
    downloadSvgAsPng(svgRef.current, `${symbol}_chart.png`)
      .then(() => {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      })
      .catch(() => setError('画像の書き出しに失敗しました（お使いのブラウザが対応していない可能性があります）'));
  };

  return (
    <div className="daily-note-chart-card">
      <NoteChart ref={svgRef} title={title} values={values} />
      <div className="daily-note-actions">
        <button type="button" onClick={handleSave}>
          {saved ? '保存しました' : '画像として保存'}
        </button>
      </div>
      {error && <p className="signal-queue-error">{error}</p>}
    </div>
  );
}
