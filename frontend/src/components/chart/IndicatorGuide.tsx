import type { ReactNode } from 'react';

// 🆕 通常チャート下段の「指標の見方」。チャート上の凡例（SMA_5 等）やサブインジケーターの
// 意味を画面内で確認できるようにする。パラメータはバックエンドの計算と一致させること
// （`services/scoring/technical_analysis.py` の既定値、`routers/stock.py` の SMA [5, 25, 75]）。
// 内容は一般的な見方の解説に留め、売買の推奨はしない。

interface GuideItem {
  term: string;
  description: string;
}

interface GuideGroup {
  id: string;
  title: string;
  items: ReadonlyArray<GuideItem>;
}

const GUIDE_GROUPS: ReadonlyArray<GuideGroup> = [
  {
    id: 'overlay',
    title: '価格チャートに重ねる指標',
    items: [
      {
        term: 'SMA_5 / SMA_25 / SMA_75',
        description:
          '単純移動平均線（Simple Moving Average）。直近5日・25日・75日の終値の平均をつないだ線で、それぞれ約1週間・約1ヶ月・約3ヶ月の平均的な売買コストを表します。株価が線より上なら上昇の流れ、下なら下降の流れと見るのが一般的です。',
      },
      {
        term: 'ゴールデンクロス / デッドクロス',
        description:
          '短期の移動平均線が長期の線を下から上へ抜けるのがゴールデンクロス（上昇転換の兆候、赤の上向き矢印）、上から下へ抜けるのがデッドクロス（下降転換の兆候、緑の下向き矢印）です。マーカーにカーソルを合わせると詳細を表示します。',
      },
      {
        term: '一目均衡表',
        description:
          '転換線（9日）・基準線（26日）・先行スパンA/B（26日先へずらして描画、2本の間が「雲」）・遅行スパン（終値を26日前へずらした線）の5本で構成されます。株価が雲より上なら強い相場、下なら弱い相場、雲の中はもみ合いと見るのが一般的です。',
      },
      {
        term: 'ボリンジャーバンド',
        description:
          '20日移動平均（Middle）と、その上下に標準偏差の2倍の幅をとった線（Upper / Lower）です。統計的には価格の多くがバンド内に収まるため、バンド幅が狭まると値動きが小さく、広がると値動きが大きくなっていることを示します。',
      },
    ],
  },
  {
    id: 'sub',
    title: '下段の指標',
    items: [
      {
        term: '出来高',
        description:
          'その期間に成立した売買の株数です。値上がりを伴って出来高が増えていれば買いの勢いが強い、というように、値動きの信頼度を測る手がかりになります。',
      },
      {
        term: 'MACD',
        description:
          '12日と26日の指数平滑移動平均（EMA）の差がMACD線、その9日EMAがSignal線、両者の差がHistogram（棒グラフ）です。MACD線がSignal線を上抜けると上昇の勢いが強まっている、下抜けると弱まっていると見るのが一般的です。0より上か下かでも強弱を判断します。',
      },
      {
        term: 'RSI',
        description:
          'Relative Strength Index（相対力指数、14日）。一定期間の値上がり幅と値下がり幅の比率を0〜100で表します。一般に70以上は買われすぎ、30以下は売られすぎの目安とされます。',
      },
      {
        term: 'ストキャスティクス（%K / %D）',
        description:
          '直近14日の高値〜安値のレンジの中で、終値がどの位置にあるかを0〜100で表します（%Kは3日平滑化、%Dはそれをさらに3日平均した線）。一般に80以上は買われすぎ、20以下は売られすぎの目安で、%Kが%Dを上抜ける／下抜ける動きを転換のサインとして見ます。',
      },
    ],
  },
];

export function IndicatorGuide(): ReactNode {
  return (
    <section className="indicator-guide" aria-labelledby="indicator-guide-heading">
      <h3 id="indicator-guide-heading" className="indicator-guide-heading">
        指標の見方
      </h3>
      <div className="indicator-guide-groups">
        {GUIDE_GROUPS.map((group) => (
          <div key={group.id} className="indicator-guide-group">
            <h4 className="indicator-guide-group-title">{group.title}</h4>
            <dl className="indicator-guide-list">
              {group.items.map((item) => (
                <div key={item.term} className="indicator-guide-item">
                  <dt>{item.term}</dt>
                  <dd>{item.description}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <p className="indicator-guide-note">
        パラメータは本画面の計算に使っている値です。いずれも一般的な見方の解説であり、売買を推奨するものではありません。60分足・15分足では出来高以外の指標（移動平均線・MACD 等）は表示されません。
      </p>
    </section>
  );
}
