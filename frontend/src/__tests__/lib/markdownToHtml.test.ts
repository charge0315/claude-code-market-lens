import { escapeHtml, markdownToHtml } from '@/lib/markdownToHtml';

describe('markdownToHtml', () => {
  it('見出し(##, ###)をh2/h3へ変換する', () => {
    expect(markdownToHtml('## 中見出し')).toBe('<h2>中見出し</h2>');
    expect(markdownToHtml('### 小見出し')).toBe('<h3>小見出し</h3>');
  });

  it('太字(**)をstrongへ変換する', () => {
    expect(markdownToHtml('**強気** な展開です')).toBe('<p><strong>強気</strong> な展開です</p>');
  });

  it('区切り線(---)をhrへ変換する', () => {
    expect(markdownToHtml('---')).toBe('<hr>');
  });

  it('箇条書き(-)をulへ変換する', () => {
    expect(markdownToHtml('- 項目1\n- 項目2')).toBe('<ul><li>項目1</li><li>項目2</li></ul>');
  });

  it('空行区切りの段落をpへ変換し、複数ブロックを結合する', () => {
    const html = markdownToHtml('## はじめに\n\n本日の分析結果です。\n\n---\n\n**方向性：強気**');

    expect(html).toBe(
      ['<h2>はじめに</h2>', '<p>本日の分析結果です。</p>', '<hr>', '<p><strong>方向性：強気</strong></p>'].join('\n'),
    );
  });

  it('段落内の改行はbrへ変換する', () => {
    expect(markdownToHtml('1行目\n2行目')).toBe('<p>1行目<br>2行目</p>');
  });

  it('HTML特殊文字をエスケープする（XSS対策）', () => {
    expect(markdownToHtml('<script>alert(1)</script>')).toBe('<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');
  });
});

describe('escapeHtml', () => {
  it('&, <, > をエスケープする', () => {
    expect(escapeHtml('A&B <tag>')).toBe('A&amp;B &lt;tag&gt;');
  });
});
