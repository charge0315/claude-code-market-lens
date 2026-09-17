import { insertNoteComChartTriggers } from '@/lib/noteComChartTriggers';

describe('insertNoteComChartTriggers', () => {
  it('銘柄見出しの直後にnote.comのチャートトリガー行を挿入する', () => {
    const body = '解説です。\n\n### 7203（トヨタ自動車）中長期・強気\n\n強気の展開です。';

    const result = insertNoteComChartTriggers(body, ['7203']);

    expect(result).toBe(
      '解説です。\n\n### 7203（トヨタ自動車）中長期・強気\n\n^7203\n\n強気の展開です。',
    );
  });

  it('複数銘柄それぞれの見出し直後に挿入する', () => {
    const body = '### 7203（トヨタ自動車）\n本文A\n\n### 9984（ソフトバンクグループ）\n本文B';

    const result = insertNoteComChartTriggers(body, ['7203', '9984']);

    expect(result).toContain('### 7203（トヨタ自動車）\n\n^7203\n本文A');
    expect(result).toContain('### 9984（ソフトバンクグループ）\n\n^9984\n本文B');
  });

  it('見出しが見つからない銘柄は挿入をスキップする（グレースフルデグレード）', () => {
    const body = '本日は該当する見出しがありません。';

    const result = insertNoteComChartTriggers(body, ['7203']);

    expect(result).toBe(body);
  });

  it('重複する証券コードは一度だけ処理する', () => {
    const body = '### 7203（トヨタ自動車）\n本文A';

    const result = insertNoteComChartTriggers(body, ['7203', '7203']);

    expect(result.match(/\^7203/g)).toHaveLength(1);
  });

  it('同一銘柄が複数見出しに登場する場合は両方に挿入する', () => {
    const body = '### 7203（トヨタ自動車）中長期\n本文A\n\n### 7203（トヨタ自動車）短期\n本文B';

    const result = insertNoteComChartTriggers(body, ['7203']);

    expect(result.match(/\^7203/g)).toHaveLength(2);
  });
});
