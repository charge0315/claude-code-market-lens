import type { ReactNode } from 'react';
import './model-lab.css';

// モデルラボ「かんたん」タブの導入説明（🆕 P14）。専門用語を避け、モデル学習初心者にも
// 「何をする画面か」「ボタンを押すと何が起きるか」が伝わることを目的にする。

export function BeginnerIntro(): ReactNode {
  return (
    <div className="model-lab-beginner-intro">
      <h3 className="model-lab-beginner-intro-title">モデルラボとは？</h3>
      <p>
        このページでは、AI が銘柄ごとの値動きを学習して「値上がりしそうか」を予測できるように
        トレーニングします。難しい設定は不要です — 下のボタンを押すだけで、あらかじめ調整済みの
        設定で自動的に学習が始まります。
      </p>
      <ul className="model-lab-beginner-intro-list">
        <li>学習データはまず米国発の株価データベース（yfinance）から取得し、データが少ない銘柄は自動的に J-Quants（東証公式データ）から補います。</li>
        <li>1回のボタン操作で、学習が済んでいない銘柄・最も長く再学習されていない銘柄から順に、いけるところまで自動で進みます。</li>
        <li>途中でブラウザを閉じても学習は止まりません。次にこのページを開いたときや、もう一度ボタンを押したときに続きから再開します。</li>
        <li>学習の精度が既存モデルを上回った場合のみ、自動的に本番モデルとして採用されます（人の承認は不要です）。</li>
      </ul>
    </div>
  );
}
