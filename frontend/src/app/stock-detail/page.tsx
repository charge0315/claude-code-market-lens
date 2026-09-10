import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';

export default function StockDetailPage(): ReactNode {
  return (
    <PageShell title="銘柄詳細" phase="P6 / P8">
      <p>チャート（複数時間軸）+ 4 分析内訳 + AI 思考トレース（ライブ / リプレイ）。</p>
    </PageShell>
  );
}
