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
import { ModelCoverageChart } from '@/components/model-lab/ModelCoverageChart';
import { ModelQualityChart } from '@/components/model-lab/ModelQualityChart';
import { TrainingTrendChart } from '@/components/model-lab/TrainingTrendChart';

// 🆕 P14: 初心者は「かんたん」タブ（学習トリガー中心）だけで完結できるようにし、
// champion/challenger 比較・PSI ドリフト・成長曲線等の既存の上級者向けセクションは
// 「詳細」タブへ切り離す（ModelLabTabs 参照、内部実装・テストは変更しない）。
//
// 🔧 P16: 各セクションが何を表しているか分かりにくいとのフィードバックを受け、
// 見出し直下に平易な説明文を追加。また学習状況グラフ（学習カバレッジ・品質分布・
// 学習の推移）は「詳細」タブだけでなく「かんたん」タブにも表示し、初心者でも
// 学習の進み具合をすぐ確認できるようにした。

const H2_STYLE = { fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' } as const;

function SimpleTab(): ReactNode {
  return (
    <>
      <BeginnerIntro />
      <section aria-labelledby="training-trigger-heading">
        <h2 id="training-trigger-heading" style={H2_STYLE}>
          銘柄別モデルの学習
        </h2>
        <TrainingTriggerPanel />
      </section>

      <section aria-labelledby="simple-coverage-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="simple-coverage-heading" style={H2_STYLE}>
          学習の状況
        </h2>
        <p className="model-lab-as-of">
          モデルタイプ（XGBoost/RandomForest/LSTM/Transformer）ごとに、東証の銘柄をどれだけ学習できたか・
          そのうち実際に予測に使われている（champion採用）銘柄がどれだけあるかを表示します。
        </p>
        <ModelCoverageChart />
      </section>

      <section aria-labelledby="simple-quality-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="simple-quality-heading" style={H2_STYLE}>
          学習の品質
        </h2>
        <p className="model-lab-as-of">
          今使われているモデル（champion）の予測精度を銘柄ごとに集計したグラフです。skillスコアは高いほど、
          RMSE は低いほど精度が高いことを意味します。
        </p>
        <ModelQualityChart />
      </section>

      <section aria-labelledby="simple-trend-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="simple-trend-heading" style={H2_STYLE}>
          学習の推移
        </h2>
        <p className="model-lab-as-of">日ごとに何銘柄のモデルを学習・更新できたかの推移です。</p>
        <TrainingTrendChart />
      </section>
    </>
  );
}

function AdvancedTab(): ReactNode {
  return (
    <>
      <section aria-labelledby="growth-heading">
        <h2 id="growth-heading" style={H2_STYLE}>
          成長曲線
        </h2>
        <p className="model-lab-as-of">
          AI全体の評価指標（勝率・IC・較正誤差・AUC・Sharpe）が、評価バッチの実行ごとにどう変化してきたかを
          表示します。右肩上がりであれば、AIの判断精度が改善していることを意味します。
        </p>
        <GrowthChart />
      </section>

      <section aria-labelledby="equity-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="equity-heading" style={H2_STYLE}>
          ピック累積成績（エクイティカーブ）
        </h2>
        <p className="model-lab-as-of">
          AIが提案したピックをすべて実行したと仮定した場合の累積損益です。ベンチマーク（TOPIX等）を上回って
          いれば、AIの銘柄選定がインデックス以上の成果を出していることになります。
        </p>
        <EquityCurveChart />
      </section>

      <section aria-labelledby="calibration-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="calibration-heading" style={H2_STYLE}>
          較正曲線
        </h2>
        <p className="model-lab-as-of">
          AIが「確度70%」と言ったとき、実際にどのくらいの確率で当たっているかを示します。対角線（点線）に
          近いほど、AIの自己評価（確信度）が信頼できることを意味します。
        </p>
        <CalibrationChart />
      </section>

      <section aria-labelledby="champions-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="champions-heading" style={H2_STYLE}>
          モデルバージョン比較（champion / challenger）
        </h2>
        <p className="model-lab-as-of">
          系統（用途）ごとに、現在本番で使われているモデル（champion）と、それを上回れるか評価中の候補
          モデル（challenger）の比較履歴です。challenger が champion を上回った場合のみ、人手承認を経て
          入れ替わります。
        </p>
        <ChampionsPanel />
      </section>

      <section aria-labelledby="drift-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="drift-heading" style={H2_STYLE}>
          PSI ドリフト
        </h2>
        <p className="model-lab-as-of">
          市場環境の変化により、AIが学習した当時の特徴量の分布から実際のデータがどれだけ乖離しているか
          （PSI値）を計測します。値が大きいほど「学習時と今の相場が違う」ことを意味し、再学習の目安になります。
        </p>
        <DriftPanel />
      </section>

      <section aria-labelledby="weekly-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="weekly-heading" style={H2_STYLE}>
          週次学習差分
        </h2>
        <p className="model-lab-as-of">
          直近1週間で、評価指標・昇格判定・ドリフト検知がどれだけ動いたかをまとめた差分です。急激な変化が
          ないか、定期的な健康チェックとして確認できます。
        </p>
        <WeeklyLearningPanel />
      </section>

      <section aria-labelledby="model-coverage-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="model-coverage-heading" style={H2_STYLE}>
          銘柄別モデルの学習カバレッジ
        </h2>
        <p className="model-lab-as-of">
          モデルタイプ（XGBoost/RandomForest/LSTM/Transformer）ごとに、東証の全銘柄のうちどれだけ学習済みか、
          その中でも実際に予測に使われている（champion採用）銘柄がどれだけあるかを示します。
        </p>
        <ModelCoverageChart />
      </section>

      <section aria-labelledby="model-quality-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="model-quality-heading" style={H2_STYLE}>
          銘柄別モデルの品質分布
        </h2>
        <p className="model-lab-as-of">
          学習済みモデルのうち、現在採用されている（champion）ものの予測精度を、銘柄ごとに集計した
          ヒストグラムです。skillスコアは高いほど、RMSEは低いほど精度が高いことを意味します。
        </p>
        <ModelQualityChart />
      </section>

      <section aria-labelledby="training-trend-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="training-trend-heading" style={H2_STYLE}>
          銘柄別モデルの学習件数の推移
        </h2>
        <p className="model-lab-as-of">
          日ごとに何銘柄のモデルを学習・更新できたかの推移です。急に0件が続く場合は、データ取得や学習処理に
          問題が起きている可能性があります。
        </p>
        <TrainingTrendChart />
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
