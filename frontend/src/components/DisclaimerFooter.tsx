import type { ReactNode } from 'react';

// 免責表示は全画面フッタに常設する（投資助言業に該当しないための恒常表示）。
export function DisclaimerFooter(): ReactNode {
  return (
    <footer
      role="contentinfo"
      style={{
        borderTop: '1px solid var(--color-border)',
        background: 'var(--color-bg-secondary)',
        color: 'var(--color-text-muted)',
        fontSize: 'var(--font-size-xs)',
        padding: 'var(--spacing-sm) var(--spacing-xl)',
        lineHeight: 1.6,
      }}
    >
      本アプリの出力は分析結果・参考情報であり、特定銘柄の売買を勧誘するものではありません。
      投資判断はご自身の責任で行ってください。本アプリはブローカーへの発注を一切行いません。
    </footer>
  );
}
