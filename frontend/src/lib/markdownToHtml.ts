// 限定的な Markdown → HTML 変換（🆕 note下書きのクリップボードコピー用）。
//
// note.com のエディタはリッチテキストで、プレーンテキストの Markdown 記法（##, ** 等）を
// そのまま貼り付けても見出し・太字には変換されない。クリップボードへ text/html も渡しておくと、
// リッチペースト時に反映される（`components/notes/DailyNoteReview.tsx` 参照）。日次noteドラフトは
// `services/notes/note_generator.py` の prompt で見出し(#/##/###)・太字(**)・区切り線(---)・
// 箇条書き(-)・表(| |)・段落のみを使うよう指示しているため、フル仕様の Markdown パーサーは導入せず
// この範囲だけを変換する（YAGNI）。表の判定は `services/notes/table_image.py`（Obsidian書き出しの
// SVG画像化）と同じGFM検出方針（区切り行 |---|---| の有無）に揃えている。

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

const TABLE_ROW_RE = /^\|.*\|$/;
const SEPARATOR_CELL_RE = /^:?-{1,}:?$/;

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isSeparatorRow(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => SEPARATOR_CELL_RE.test(cell));
}

function isTableBlock(lines: string[]): boolean {
  return lines.length >= 2 && lines.every((l) => TABLE_ROW_RE.test(l)) && isSeparatorRow(lines[1]);
}

function tableToHtml(lines: string[]): string {
  const [headerLine, , ...dataLines] = lines;
  const header = splitTableRow(headerLine);
  const thead = `<tr>${header.map((c) => `<th>${inlineToHtml(c)}</th>`).join('')}</tr>`;
  const tbody = dataLines
    .map((line) => `<tr>${splitTableRow(line).map((c) => `<td>${inlineToHtml(c)}</td>`).join('')}</tr>`)
    .join('');
  return `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
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

  if (isTableBlock(lines)) {
    return tableToHtml(lines);
  }

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
