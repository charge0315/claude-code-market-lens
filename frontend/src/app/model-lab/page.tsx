import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { BeginnerIntro } from '@/components/model-lab/BeginnerIntro';
import { InfoPopoverButton } from '@/components/model-lab/InfoPopoverButton';
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
import { ModelQualitySummaryLine } from '@/components/model-lab/ModelQualitySummaryLine';
import { TrainingTrendChart } from '@/components/model-lab/TrainingTrendChart';
import { TrainingTrendSummaryLine } from '@/components/model-lab/TrainingTrendSummaryLine';
import { PitCoveragePanel } from '@/components/model-lab/PitCoveragePanel';
import { PitCoverageSummaryLine } from '@/components/model-lab/PitCoverageSummaryLine';
import { AblationPanel } from '@/components/model-lab/AblationPanel';

// 🆕 P14: 初心者は「かんたん」タブ（学習トリガー中心）だけで完結できるようにし、
// champion/challenger 比較・PSI ドリフト・成長曲線等の既存の上級者向けセクションは
// 「詳細」タブへ切り離す（ModelLabTabs 参照、内部実装・テストは変更しない）。
//
// 🔧 P16: 各セクションが何を表しているか分かりにくいとのフィードバックを受け、
// 見出し直下に平易な説明文を追加。また学習状況グラフ（学習カバレッジ・品質分布・
// 学習の推移）は「詳細」タブだけでなく「かんたん」タブにも表示し、初心者でも
// 学習の進み具合をすぐ確認できるようにした。
//
// 🔧 学習の品質・学習の推移は「かんたん」タブでは1行サマリーへ簡略化した（ユーザー指示）。
// モデルタイプ・指標を切り替えられる詳細なグラフ（`ModelQualityChart`/`TrainingTrendChart`）
// は「詳細」タブに残す。

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
          今使われているモデル（champion）の予測精度を銘柄ごとに集計したものです。skillスコアは高いほど、
          RMSE は低いほど精度が高いことを意味します。
        </p>
        <ModelQualitySummaryLine />
      </section>

      <section aria-labelledby="simple-trend-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="simple-trend-heading" style={H2_STYLE}>
          学習の推移
        </h2>
        <p className="model-lab-as-of">日ごとに何銘柄のモデルを学習・更新できたかの推移です。</p>
        <TrainingTrendSummaryLine />
      </section>

      <section aria-labelledby="simple-pit-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="simple-pit-heading" style={H2_STYLE}>
          Vault情報の学習活用
        </h2>
        <PitCoverageSummaryLine />
      </section>
    </>
  );
}

function AdvancedTab(): ReactNode {
  return (
    <>
      <div className="model-lab-chart-grid">
        <section aria-labelledby="growth-heading" className="model-lab-detail-card">
          <div className="model-lab-heading-row">
            <h2 id="growth-heading" style={H2_STYLE}>
              成長曲線
            </h2>
            <InfoPopoverButton title="成長曲線とは">
              <div className="ml-info-body">
                <p>
                  AI全体の評価指標が、評価バッチ（決着済みピックがまとまった時点で自動実行される再評価）の
                  実行ごとにどう変化してきたかを折れ線で表示します。1回の評価バッチが1点になります。
                </p>
                <p>指標は5種類から選べます（scope で中長期/短期/合算も切り替え可能）。</p>
                <ul>
                  <li><strong>勝率</strong> — 決着済みピックのうち、方向が当たった割合。</li>
                  <li><strong>IC（情報係数）</strong> — AIの予測順位と実際の値動き順位の相関。1に近いほど順位付けが正確。</li>
                  <li><strong>較正誤差</strong> — 確度の自己申告と実測正解率のズレ（小さいほど良い）。</li>
                  <li><strong>AUC</strong> — 上がる/下がるの二値分類としての判別力（0.5=ランダム、1.0=完全）。</li>
                  <li><strong>Sharpe</strong> — ピックの損益をリスク（振れ幅）で割った効率性の指標。</li>
                </ul>
                <p>
                  右肩上がりであればAIの判断精度が改善していることを意味しますが、評価バッチの回数（＝決着済み
                  ピックの蓄積量）が少ないうちは1点ごとの振れ幅が大きく出ます。点数が少ない段階では傾向を
                  断定せず、参考値として見てください。
                </p>
              </div>
            </InfoPopoverButton>
          </div>
          <p className="model-lab-as-of">
            AI全体の評価指標（勝率・IC・較正誤差・AUC・Sharpe）が、評価バッチの実行ごとにどう変化してきたかを
            表示します。右肩上がりであれば、AIの判断精度が改善していることを意味します。
          </p>
          <GrowthChart />
        </section>

        <section aria-labelledby="equity-heading" className="model-lab-detail-card">
          <div className="model-lab-heading-row">
            <h2 id="equity-heading" style={H2_STYLE}>
              ピック累積成績（エクイティカーブ）
            </h2>
            <InfoPopoverButton title="ピック累積成績（エクイティカーブ）とは">
              <div className="ml-info-body">
                <p>
                  AIが提案したピックを、推奨買値で建てて推奨損切値/推奨売値のどちらかに到達した時点で
                  決済したと仮定した場合の累積損益を時系列で積み上げたグラフです。ベンチマーク（TOPIX等）の
                  同期間の推移と重ねて表示し、AIの銘柄選定に実際のインデックス投資を上回る価値があるかを
                  見るためのものです。
                </p>
                <p>
                  ホライズン（20/60営業日）は「その日数までに損切/利確ラインへ到達しなければ強制決済した
                  とみなす」打ち切り期間です。scope で中長期/短期/合算を切り替えられます。
                </p>
                <p>
                  あくまで「全ピックを機械的に実行し続けたら」という仮定の試算であり、売買手数料・スリッページ・
                  資金配分（同時に何銘柄保有するか）は考慮していません。実際の運用成績を保証するものではなく、
                  相対的な傾向（ベンチマークを上回っているか）を確認する目的で使ってください。
                </p>
              </div>
            </InfoPopoverButton>
          </div>
          <p className="model-lab-as-of">
            AIが提案したピックをすべて実行したと仮定した場合の累積損益です。ベンチマーク（TOPIX等）を上回って
            いれば、AIの銘柄選定がインデックス以上の成果を出していることになります。
          </p>
          <EquityCurveChart />
        </section>

        <section aria-labelledby="calibration-heading" className="model-lab-detail-card">
          <div className="model-lab-heading-row">
            <h2 id="calibration-heading" style={H2_STYLE}>
              較正曲線
            </h2>
            <InfoPopoverButton title="較正曲線とは">
              <div className="ml-info-body">
                <p>
                  横軸にAIが申告した確度（例: 70%）、縦軸にその確度帯で実際にピックが的中した割合（実測勝率）を
                  プロットしたグラフです。点線の対角線は「申告どおりに当たっている」理想の状態を表します。
                </p>
                <p>
                  点が対角線より<strong>上</strong>にある場合はAIが自分の確信度を過小評価している（実際はもっと
                  当たっている）状態、<strong>下</strong>にある場合は過大評価している（申告ほど当たっていない）
                  状態を意味します。対角線に近いほど、UIに表示される確度バケット（高/中/低）を額面どおり
                  信頼できることになります。
                </p>
                <p>
                  この確度は生の予測値をそのまま使うのではなく、isotonic回帰やPlatt scaling（`CALIBRATION_METHOD`
                  設定）で事後補正した後の値です。台帳（決着済みピック）が薄いうちは補正を適用せず恒等
                  フォールバックになるため、初期は対角線に近づきにくい点に留意してください。
                </p>
              </div>
            </InfoPopoverButton>
          </div>
          <p className="model-lab-as-of">
            AIが「確度70%」と言ったとき、実際にどのくらいの確率で当たっているかを示します。対角線（点線）に
            近いほど、AIの自己評価（確信度）が信頼できることを意味します。
          </p>
          <CalibrationChart />
        </section>
      </div>

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

      <section aria-labelledby="pit-coverage-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <div className="model-lab-heading-row">
          <h2 id="pit-coverage-heading" style={H2_STYLE}>
            Vault特徴量（PIT）の収集進捗
          </h2>
          <InfoPopoverButton title="PIT（point-in-time）特徴量とは">
            <div className="ml-info-body">
              <p>
                Obsidian Vaultに補完された銘柄の決算情報・ニュースセンチメントを、AIの学習（断面プールモデル）へ
                取り込むための日次スナップショットです。Vaultのノートは日々上書きされる「現在値」のため、
                過去の学習データへそのまま結合すると未来の情報が混ざってしまいます（意図しない先読み）。
              </p>
              <p>
                そのため、今日から先の値を毎日記録し、必要な営業日数（既定60営業日）が貯まったグループから
                順に自動的に学習特徴量へ組み込まれます。
              </p>
            </div>
          </InfoPopoverButton>
        </div>
        <PitCoveragePanel />
      </section>

      <section aria-labelledby="ablation-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <div className="model-lab-heading-row">
          <h2 id="ablation-heading" style={H2_STYLE}>
            ソースアブレーション評価
          </h2>
          <InfoPopoverButton title="ソースアブレーション評価とは">
            <div className="ml-info-body">
              <p>
                ある情報源（例: Vault決算情報）を除外して再学習し、含めた場合と比べて予測精度がどれだけ
                変わるかを四半期ごとに測定します。「Vault由来の特徴量を足して本当に良くなったか」を確認できる
                唯一の客観的な材料です。
              </p>
              <p>差分がマイナスであるほど、その情報源が精度に貢献していることを意味します。</p>
            </div>
          </InfoPopoverButton>
        </div>
        <AblationPanel />
      </section>
    </>
  );
}

export default function ModelLabPage(): ReactNode {
  return (
    <PageShell title="モデルラボ" badge="自動学習ダッシュボード">
      <ModelLabTabs simple={<SimpleTab />} advanced={<AdvancedTab />} />
    </PageShell>
  );
}
