// 限定的な Markdown → HTML 変換（🆕 note下書きのクリップボードコピー用）。
//
// note.com のエディタはリッチテキストで、プレーンテキストの Markdown 記法（##, ** 等）を
// そのまま貼り付けても見出し・太字には変換されない。クリップボードへ text/html も渡しておくと、
// リッチペースト時に反映される（`components/notes/DailyNoteReview.tsx` 参照）。日次noteドラフトは
// `services/notes/note_generator.py` の prompt で見出し(#/##/###)・太字(**)・区切り線(---)・
// 箇条書き(-)・段落のみを使うよう指示しているため、フル仕様の Markdown パーサーは導入せず
// この範囲だけを変換する（YAGNI）。

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineToHtml(text: string): string {
  const escaped = escapeHtml(text);
  const bolded = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  return bolded.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, '<em>$1</em>');
}

function isBulletLine(line: string): boolean {
  return /^[-*]\s+/.test(line);
}

function blockToHtml(block: string): string {
  const trimmed = block.trim();

  if (/^-{3,}$/.test(trimmed)) {
    return '<hr>';
  }

  const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
  if (headingMatch) {
    const level = headingMatch[1].length;
    return `<h${level}>${inlineToHtml(headingMatch[2])}</h${level}>`;
  }

  const lines = trimmed
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  if (lines.length > 0 && lines.every(isBulletLine)) {
    const items = lines.map((l) => `<li>${inlineToHtml(l.replace(/^[-*]\s+/, ''))}</li>`).join('');
    return `<ul>${items}</ul>`;
  }

  return `<p>${lines.map(inlineToHtml).join('<br>')}</p>`;
}

export function markdownToHtml(markdown: string): string {
  return markdown
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map(blockToHtml)
    .join('\n');
}
