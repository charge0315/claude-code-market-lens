// JST（`Asia/Tokyo`）基準の日付ユーティリティ。ブラウザのローカルタイムゾーンに依存せず、
// 常に日本時間の「今日」を `YYYY-MM-DD` で返す（CLAUDE.md: 時刻は JST）。

const JST_FORMATTER = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' });

export function todayJst(): string {
  // sv-SE ロケールは `YYYY-MM-DD` 形式を返すため、そのまま ISO 日付として使える。
  return JST_FORMATTER.format(new Date());
}
