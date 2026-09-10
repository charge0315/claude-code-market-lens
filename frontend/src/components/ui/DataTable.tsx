import type { ReactNode } from 'react';
import './datatable.css';

// 生 <table> の直書きを禁止し、テーブルは必ずこのコンポーネント経由にする（プロ端末規約）。
// caption は必須（スクリーンリーダ向けの表の説明）。数値列は align='end' で
// 等幅・右寄せ（.num）にする。

export interface Column<Row> {
  /** 行オブジェクトのキー、または算出セルのための任意 id */
  key: string;
  header: string;
  /** 省略時は row[key] をそのまま表示 */
  render?: (row: Row) => ReactNode;
  align?: 'start' | 'end' | 'center';
  /** 数値列（等幅・右寄せ）にするか */
  numeric?: boolean;
}

interface DataTableProps<Row> {
  /** 表全体の説明。視覚的には非表示だが必須 */
  caption: string;
  columns: ReadonlyArray<Column<Row>>;
  rows: ReadonlyArray<Row>;
  /** 行の一意キーを返す */
  rowKey: (row: Row, index: number) => string;
  /** 行が無いときの案内 */
  emptyMessage?: string;
}

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  emptyMessage = 'データがありません',
}: DataTableProps<Row>): ReactNode {
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={col.numeric ? 'num' : undefined}
                style={{ textAlign: col.align ?? (col.numeric ? 'end' : 'start') }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="data-table-empty">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={rowKey(row, i)}>
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={col.numeric ? 'num' : undefined}
                    style={{ textAlign: col.align ?? (col.numeric ? 'end' : 'start') }}
                  >
                    {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
