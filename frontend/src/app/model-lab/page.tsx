import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { GrowthChart } from '@/components/model-lab/GrowthChart';
import { CalibrationChart } from '@/components/model-lab/CalibrationChart';
import { ChampionsPanel } from '@/components/model-lab/ChampionsPanel';
import { DriftPanel } from '@/components/model-lab/DriftPanel';
import { WeeklyLearningPanel } from '@/components/model-lab/WeeklyLearningPanel';

export default function ModelLabPage(): ReactNode {
  return (
    <PageShell title="モデルラボ" phase="P8">
      <p>精度の成長曲線（AUC / IC / 較正誤差 / 勝率）、Calibration curve、モデルバージョン比較、再学習ログ、PSI ドリフト、週次学習差分。</p>

      <section aria-labelledby="growth-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="growth-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          成長曲線
        </h2>
        <GrowthChart />
      </section>

      <section aria-labelledby="calibration-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="calibration-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          較正曲線
        </h2>
        <CalibrationChart />
      </section>

      <section aria-labelledby="champions-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="champions-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          モデルバージョン比較（champion / challenger）
        </h2>
        <ChampionsPanel />
      </section>

      <section aria-labelledby="drift-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="drift-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          PSI ドリフト
        </h2>
        <DriftPanel />
      </section>

      <section aria-labelledby="weekly-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="weekly-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          週次学習差分
        </h2>
        <WeeklyLearningPanel />
      </section>
    </PageShell>
  );
}
