import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { BeginnerIntro } from '@/components/model-lab/BeginnerIntro';
import { ModelLabTabs } from '@/components/model-lab/ModelLabTabs';
import { GrowthChart } from '@/components/model-lab/GrowthChart';
import { EquityCurveChart } from '@/components/model-lab/EquityCurveChart';
import { CalibrationChart } from '@/components/model-lab/CalibrationChart';
import { ChampionsPanel } from '@/components/model-lab/ChampionsPanel';
import { DriftPanel } from '@/components/model-lab/DriftPanel';
import { TrainingTriggerPanel } from '@/components/model-lab/TrainingTriggerPanel';
import { WeeklyLearningPanel } from '@/components/model-lab/WeeklyLearningPanel';

// 🆕 P14: 初心者は「かんたん」タブ（学習トリガー中心）だけで完結できるようにし、
// champion/challenger 比較・PSI ドリフト・成長曲線等の既存の上級者向けセクションは
// 「詳細」タブへ切り離す（ModelLabTabs 参照、内部実装・テストは変更しない）。

function SimpleTab(): ReactNode {
  return (
    <>
      <BeginnerIntro />
      <section aria-labelledby="training-trigger-heading">
        <h2 id="training-trigger-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          銘柄別モデルの学習
        </h2>
        <TrainingTriggerPanel />
      </section>
    </>
  );
}

function AdvancedTab(): ReactNode {
  return (
    <>
      <section aria-labelledby="growth-heading">
        <h2 id="growth-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          成長曲線
        </h2>
        <GrowthChart />
      </section>

      <section aria-labelledby="equity-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="equity-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          ピック累積成績（エクイティカーブ）
        </h2>
        <EquityCurveChart />
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
    </>
  );
}

export default function ModelLabPage(): ReactNode {
  return (
    <PageShell title="モデルラボ">
      <ModelLabTabs simple={<SimpleTab />} advanced={<AdvancedTab />} />
    </PageShell>
  );
}
