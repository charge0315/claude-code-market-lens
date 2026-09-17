// note.comの証券コード埋め込み機能（🆕 ユーザー指示）。
//
// note.com のエディタは「^5243」（日本株）のように証券コードを入力してEnterキーを押すと、
// 株価チャートを記事内に自動表示する機能を持つ（ユーザー確認済み仕様。米国株は「$GOOG」だが
// Alpha Forgeは日本株のみを扱うため「^」+4桁証券コードの形式のみ対応する）。
//
// 日次noteドラフトの本文は、各ピック銘柄の見出しを「### {証券コード}（{銘柄名}）...」の形式で
// 書くようLLMに指示している（`services/notes/note_generator.py` の
// `_TEMPLATE_STRUCTURE_INSTRUCTIONS` 参照）。その見出し直後にトリガー行を挿入することで、
// note.comへ貼り付けた記事の該当銘柄の直後にチャートを配置できるようにする。
//
// この変換は「本文をコピー」時（copyNoteToClipboard）にのみ適用し、DBに保存される
// body_markdown 自体は書き換えない。Obsidianは行頭の「^」をブロック参照IDとして解釈するため、
// Obsidian書き出し側（note_export.py）には一切適用しない。
//
// LLM出力の見出しがテンプレートから逸脱し該当銘柄の見出しが見つからない場合は、その銘柄への
// 挿入をスキップする（貼り付け自体を失敗させないグレースフルデグレード）。

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function insertNoteComChartTriggers(bodyMarkdown: string, symbols: string[]): string {
  const uniqueSymbols = Array.from(new Set(symbols));
  let result = bodyMarkdown;
  for (const symbol of uniqueSymbols) {
    const pattern = new RegExp(`^###\\s+${escapeRegExp(symbol)}\\b.*$`, 'gm');
    const matches = Array.from(result.matchAll(pattern));
    for (const match of matches.reverse()) {
      const insertAt = (match.index ?? 0) + match[0].length;
      result = `${result.slice(0, insertAt)}\n\n^${symbol}${result.slice(insertAt)}`;
    }
  }
  return result;
}
