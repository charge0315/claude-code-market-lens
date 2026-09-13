'use client';

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import {
  approveSignal,
  fetchSignals,
  rejectSignal,
  reportFill,
  type PortfolioSignal,
  type PortfolioSignalStatus,
} from '@/lib/api/portfolio';
import './portfolio.css';

// AI 売買タイミング判定の承認キュー（HITL）。承認/却下/実約定報告はすべて人間が行う
// （アプリは一切発注しない、CLAUDE.md）。

const ACTION_LABELS: Record<PortfolioSignal['action'], string> = {
  hold: '継続保有',
  trim: '一部利確',
  stop_loss: '損切り',
  add: '買い増し',
};

const STATUS_LABELS: Record<PortfolioSignalStatus, string> = {
  proposed: '未承認',
  approved: '承認済み',
  rejected: '却下',
  executed: '約定済み',
};

const STATUS_TABS: ReadonlyArray<PortfolioSignalStatus | 'all'> = ['proposed', 'approved', 'rejected', 'executed', 'all'];

function formatYen(value: number | null): string {
  return value === null ? '—' : `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function ReportFillForm({
  signalId,
  onSubmitted,
  onCancel,
}: {
  signalId: string;
  onSubmitted: () => void;
  onCancel: () => void;
}): ReactNode {
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: FormEvent): void => {
    e.preventDefault();
    setError(null);
    const executedPrice = Number(price);
    const executedQuantity = Number(quantity);
    if (!Number.isFinite(executedPrice) || executedPrice <= 0) {
      setError('約定価格は正の数値で入力してください');
      return;
    }
    if (!Number.isInteger(executedQuantity) || executedQuantity <= 0) {
      setError('約定株数は正の整数で入力してください');
      return;
    }
    setSubmitting(true);
    reportFill(signalId, {
      executed_price: executedPrice,
      executed_quantity: executedQuantity,
      executed_at: new Date().toISOString(),
      note: note || null,
    })
      .then(() => onSubmitted())
      .catch(() => setError('実約定報告に失敗しました'))
      .finally(() => setSubmitting(false));
  };

  return (
    <form className="signal-fill-form" onSubmit={handleSubmit} aria-label="実約定結果の報告">
      <label>
        約定価格（円）
        <input
          type="number"
          inputMode="decimal"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          required
        />
      </label>
      <label>
        約定株数
        <input type="number" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
      </label>
      <label>
        メモ（任意）
        <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && <p className="signal-queue-error">{error}</p>}
      <div className="signal-fill-form-actions">
        <button type="submit" disabled={submitting}>
          報告する
        </button>
        <button type="button" onClick={onCancel} disabled={submitting}>
          キャンセル
        </button>
      </div>
    </form>
  );
}

export function SignalQueue(): ReactNode {
  const [statusFilter, setStatusFilter] = useState<PortfolioSignalStatus | 'all'>('proposed');
  const [signals, setSignals] = useState<PortfolioSignal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [fillingId, setFillingId] = useState<string | null>(null);

  const load = useCallback((status: PortfolioSignalStatus | 'all') => {
    fetchSignals(status === 'all' ? undefined : { status })
      .then(setSignals)
      .catch(() => setError('判定一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    load(statusFilter);
  }, [load, statusFilter]);

  const handleApprove = (signalId: string): void => {
    setBusyId(signalId);
    approveSignal(signalId)
      .then(() => load(statusFilter))
      .catch(() => setError('承認に失敗しました'))
      .finally(() => setBusyId(null));
  };

  const handleReject = (signalId: string): void => {
    setBusyId(signalId);
    rejectSignal(signalId)
      .then(() => load(statusFilter))
      .catch(() => setError('却下に失敗しました'))
      .finally(() => setBusyId(null));
  };

  return (
    <div className="signal-queue">
      <div className="signal-queue-tabs" role="group" aria-label="判定の状態フィルタ">
        {STATUS_TABS.map((status) => (
          <button
            key={status}
            type="button"
            className={statusFilter === status ? 'is-active' : undefined}
            aria-pressed={statusFilter === status}
            onClick={() => setStatusFilter(status)}
          >
            {status === 'all' ? 'すべて' : STATUS_LABELS[status]}
          </button>
        ))}
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {signals.length === 0 ? (
        <p className="signal-queue-empty">該当する判定がありません</p>
      ) : (
        <ul className="signal-queue-list">
          {signals.map((signal) => (
            <li key={signal.signal_id} className="signal-card">
              <div className="signal-card-header">
                <span className="signal-card-symbol">{signal.symbol}</span>
                <span className="signal-card-engine-badge">Claude</span>
                <span className={`signal-card-action signal-card-action--${signal.action}`}>
                  {ACTION_LABELS[signal.action]}
                </span>
                <span className="signal-card-status">{STATUS_LABELS[signal.status]}</span>
              </div>
              <p className="signal-card-rationale">{signal.rationale}</p>
              <dl className="signal-card-bracket">
                {signal.entry !== null && (
                  <div>
                    <dt>買値目安</dt>
                    <dd>{formatYen(signal.entry)}</dd>
                  </div>
                )}
                <div>
                  <dt>損切り</dt>
                  <dd>{formatYen(signal.stop)}</dd>
                </div>
                <div>
                  <dt>利確目標</dt>
                  <dd>{formatYen(signal.target)}</dd>
                </div>
                <div>
                  <dt>確信度</dt>
                  <dd>{signal.confidence.toFixed(0)}</dd>
                </div>
              </dl>

              {signal.gemini_shadow && (
                <div className="signal-card-shadow">
                  <div className="signal-card-header">
                    <span className="signal-card-engine-badge signal-card-engine-badge--gemini">Gemini（比較）</span>
                    <span className={`signal-card-action signal-card-action--${signal.gemini_shadow.action}`}>
                      {ACTION_LABELS[signal.gemini_shadow.action]}
                    </span>
                  </div>
                  <p className="signal-card-rationale">{signal.gemini_shadow.reasoning}</p>
                  <dl className="signal-card-bracket">
                    {signal.gemini_shadow.entry !== null && (
                      <div>
                        <dt>買値目安</dt>
                        <dd>{formatYen(signal.gemini_shadow.entry)}</dd>
                      </div>
                    )}
                    <div>
                      <dt>損切り</dt>
                      <dd>{formatYen(signal.gemini_shadow.stop)}</dd>
                    </div>
                    <div>
                      <dt>利確目標</dt>
                      <dd>{formatYen(signal.gemini_shadow.target)}</dd>
                    </div>
                    <div>
                      <dt>確信度</dt>
                      <dd>{signal.gemini_shadow.confidence.toFixed(0)}</dd>
                    </div>
                  </dl>
                </div>
              )}

              {signal.status === 'proposed' && (
                <div className="signal-card-actions">
                  <button type="button" onClick={() => handleApprove(signal.signal_id)} disabled={busyId === signal.signal_id}>
                    承認
                  </button>
                  <button type="button" onClick={() => handleReject(signal.signal_id)} disabled={busyId === signal.signal_id}>
                    却下
                  </button>
                </div>
              )}

              {signal.status === 'approved' &&
                (fillingId === signal.signal_id ? (
                  <ReportFillForm
                    signalId={signal.signal_id}
                    onSubmitted={() => {
                      setFillingId(null);
                      load(statusFilter);
                    }}
                    onCancel={() => setFillingId(null)}
                  />
                ) : (
                  <div className="signal-card-actions">
                    <button type="button" onClick={() => setFillingId(signal.signal_id)}>
                      実約定を報告
                    </button>
                  </div>
                ))}

              {signal.status === 'executed' && signal.fill_report && (
                <p className="signal-card-fill-report">約定報告済み</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
