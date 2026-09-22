// `lightweight-charts` の `Time` 型ヘルパー（`PriceChart`/`MultiChart` 共通）。

import type { Time, UTCTimestamp } from 'lightweight-charts';

// `OhlcBar.time`（日足=YYYY-MM-DD文字列、分足=Unix秒）を `lightweight-charts` の `Time` へ
// 変換する。ライブラリの `Time` は文字列と数値を区別できないため、数値は `UTCTimestamp` へ
// 明示キャストする（公式ドキュメント推奨の書き方）。
export function toChartTime(time: string | number): Time {
  return typeof time === 'number' ? (time as UTCTimestamp) : time;
}
