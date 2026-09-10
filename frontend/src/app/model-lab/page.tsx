import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';

export default function ModelLabPage(): ReactNode {
  return (
    <PageShell title="モデルラボ" phase="P5 / P8">
      <p>精度の成長曲線（AUC / IC / 較正誤差 / 勝率）、Calibration curve、モデルバージョン比較、再学習ログ、PSI ドリフト、週次学習差分。</p>
    </PageShell>
  );
}
