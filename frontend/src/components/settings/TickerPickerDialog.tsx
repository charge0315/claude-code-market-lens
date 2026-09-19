'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Modal } from '@/components/ui/Modal';
import { DataTable, type Column } from '@/components/ui/DataTable';
import {
  fetchTickerUniverse,
  updateTrainingTargetTickers,
  type TickerUniverseEntry,
  type TickerUniverseSort,
} from '@/lib/api/registry';
import './ticker-picker.css';

const QUERY_DEBOUNCE_MS = 300;
// 東証全銘柄（約4000件）を無条件に描画すると重いため、業種/検索で絞り込まれていない
// ときだけ表示件数を制限する（選択状態自体は全件を対象に正しく保持する）。
const MAX_UNFILTERED_ROWS = 300;

// 学習対象「カスタムリスト」の銘柄選択ポップアップ（🆕）。業種フィルタ・出来高ソート・
// 検索で絞り込みつつ、チェックボックスで追加/削除する。保存は選択集合の全置換
// （`PUT /registry/training-target-tickers`）で行う（既存銘柄の追加日時はサーバ側で維持される）。

export function TickerPickerDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }): ReactNode {
  const [sectorOptions, setSectorOptions] = useState<string[]>([]);
  const [volumeAvailable, setVolumeAvailable] = useState(false);
  const [entries, setEntries] = useState<TickerUniverseEntry[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sector, setSector] = useState('');
  const [sort, setSort] = useState<TickerUniverseSort>('code_asc');
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initializedSelectionRef = useRef(false);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 業種の選択肢・出来高有無・選択集合の初期値は、フィルタ前の全件取得から一度だけ確定する
  // （業種フィルタをかけた後の一覧から算出すると、選んだ業種しか選択肢に残らなくなるため）。
  useEffect(() => {
    fetchTickerUniverse()
      .then((res) => {
        setSectorOptions(Array.from(new Set(res.map((e) => e.sector).filter((s): s is string => !!s))).sort());
        setVolumeAvailable(res.some((e) => e.volume !== null));
        if (!initializedSelectionRef.current) {
          setSelected(new Set(res.filter((e) => e.in_custom_list).map((e) => e.code)));
          initializedSelectionRef.current = true;
        }
      })
      .catch(() => setError('銘柄一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setQuery(queryInput.trim()), QUERY_DEBOUNCE_MS);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [queryInput]);

  useEffect(() => {
    fetchTickerUniverse({ sector: sector || undefined, sort, q: query || undefined })
      .then(setEntries)
      .catch(() => setError('銘柄一覧の取得に失敗しました'));
  }, [sector, sort, query]);

  const toggle = (code: string): void => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const isUnfiltered = sector === '' && query === '';
  const displayEntries = isUnfiltered ? entries.slice(0, MAX_UNFILTERED_ROWS) : entries;

  const handleSave = (): void => {
    setSaving(true);
    setError(null);
    updateTrainingTargetTickers(Array.from(selected))
      .then(() => {
        onSaved();
        onClose();
      })
      .catch(() => setError('学習対象銘柄リストの保存に失敗しました'))
      .finally(() => setSaving(false));
  };

  const columns: Column<TickerUniverseEntry>[] = [
    {
      key: 'checked',
      header: '選択',
      render: (row) => (
        <input
          type="checkbox"
          checked={selected.has(row.code)}
          onChange={() => toggle(row.code)}
          aria-label={`${row.code}（${row.name}）を学習対象に含める`}
        />
      ),
    },
    { key: 'code', header: 'コード' },
    { key: 'name', header: '銘柄名' },
    { key: 'sector', header: '業種', render: (row) => row.sector ?? '—' },
    {
      key: 'volume',
      header: '出来高',
      numeric: true,
      render: (row) => (row.volume !== null ? Math.round(row.volume).toLocaleString() : '—'),
    },
  ];

  return (
    <Modal title="学習対象銘柄リストの編集" onClose={onClose}>
      <div className="ticker-picker">
        {error && <p className="signal-queue-error">{error}</p>}

        <div className="ticker-picker-filters">
          <label className="ticker-picker-filter-field">
            業種
            <select value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">すべて</option>
              {sectorOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="ticker-picker-filter-field">
            並び順
            <select value={sort} onChange={(e) => setSort(e.target.value as TickerUniverseSort)}>
              <option value="code_asc">コード順</option>
              <option value="volume_desc" disabled={!volumeAvailable}>
                出来高が多い順
              </option>
              <option value="volume_asc" disabled={!volumeAvailable}>
                出来高が少ない順
              </option>
            </select>
          </label>
          <label className="ticker-picker-filter-field ticker-picker-search">
            検索
            <input
              type="search"
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="証券コード または 銘柄名"
            />
          </label>
        </div>

        {!volumeAvailable && (
          <p className="ticker-picker-notice">
            J-Quants 未設定のため出来高データがありません。出来高ソートは無効になっています。
          </p>
        )}
        {isUnfiltered && entries.length > MAX_UNFILTERED_ROWS && (
          <p className="ticker-picker-notice">
            {entries.length.toLocaleString()} 銘柄中、上位 {MAX_UNFILTERED_ROWS} 件のみ表示しています。業種や検索で絞り込んでください。
          </p>
        )}

        <div className="ticker-picker-table">
          <DataTable
            caption="学習対象銘柄の選択"
            columns={columns}
            rows={displayEntries}
            rowKey={(row) => row.code}
            emptyMessage="該当する銘柄がありません"
          />
        </div>

        <div className="ticker-picker-footer">
          <span className="ticker-picker-selected-count">{selected.size} 銘柄を選択中</span>
          <button type="button" onClick={handleSave} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </Modal>
  );
}
