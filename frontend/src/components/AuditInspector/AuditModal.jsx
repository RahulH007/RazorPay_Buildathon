import { useState, useEffect } from 'react';
import { Search, X, ShieldCheck, AlertCircle, FileText, CheckCircle2 } from 'lucide-react';
import api from '../../utils/api';
import { formatCurrencyFull, FAILURE_CLASS_LABELS } from '../../utils/formatters';
import AuditEntry from './AuditEntry';

export default function AuditModal({ record, onClose }) {
  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!record) return undefined;
    let cancelled = false;
    setLoading(true);
    api
      .getAudit(record.payment_id)
      .then((data) => {
        if (!cancelled) {
          setAuditData(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [record]);

  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  if (!record) return null;

  const summary = [
    { label: 'Amount', value: formatCurrencyFull(record.amount) },
    {
      label: 'Classification',
      value: FAILURE_CLASS_LABELS[record.failure_class] || record.failure_class || 'Transient Technical',
    },
    { label: 'State', value: record.recovery_state },
    { label: 'Channel', value: record.recovery_channel || 'Auto Selected' },
    { label: 'Customer', value: record.customer_name },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#162F56]/40 p-4 backdrop-blur-sm animate-overlay-in"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--rzp-border)] bg-white shadow-[0_24px_70px_rgba(22,47,86,0.18)] animate-modal-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--rzp-border)] px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--rzp-blue-050)] text-[var(--rzp-blue-600)]">
              <Search size={16} strokeWidth={2.2} />
            </span>
            <div>
              <div className="flex items-center gap-2 text-base font-bold text-[var(--rzp-ink)]">
                <span>Audit Inspector</span>
                <span className="rounded-full border border-[#A6F4C5] bg-[#ECFDF3] px-2 py-0.5 font-mono text-[10px] font-bold text-[var(--rzp-green-dark)]">
                  Hash-chained
                </span>
              </div>
              <div className="mt-0.5 font-mono text-xs text-[var(--rzp-ink-muted)]">{record.payment_id}</div>
            </div>
          </div>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--rzp-border)] text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)] hover:text-[var(--rzp-ink)]"
            onClick={onClose}
            aria-label="Close audit inspector"
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {/* Summary chips */}
        <div className="flex shrink-0 flex-wrap gap-2 border-b border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-6 py-3">
          {summary.map(({ label, value }) => (
            <span
              key={label}
              className="rounded-lg border border-[var(--rzp-border)] bg-white px-3 py-1.5"
            >
              <span className="mr-2 font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
                {label}
              </span>
              <span className="font-mono text-xs font-semibold text-[var(--rzp-ink)]">{value}</span>
            </span>
          ))}
          {auditData && (
            <span className="rounded-lg border border-[#A6F4C5] bg-[#ECFDF3] px-3 py-1.5">
              <span className="mr-2 font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--rzp-green-dark)]">
                Total Spend
              </span>
              <span className="font-mono text-xs font-bold text-[var(--rzp-green-dark)]">
                ₹{auditData.total_cost_inr?.toFixed(2) || '0.00'}
              </span>
            </span>
          )}
        </div>

        {/* Timeline */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4 space-y-2 custom-scrollbar">
          {loading ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center font-mono text-xs text-[var(--rzp-ink-muted)]">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--rzp-blue-600)] border-t-transparent" />
              <span>Fetching ledger audit trail...</span>
            </div>
          ) : auditData?.audit_trail?.length > 0 ? (
            <div className="space-y-2">
              {auditData.audit_trail.map((entry, i) => (
                <AuditEntry
                  key={i}
                  entry={entry}
                  isHardDecline={
                    entry.action?.includes('WHY_WE_DIDNT_ACT') ||
                    entry.action?.includes('HARD_DECLINE')
                  }
                />
              ))}
            </div>
          ) : (
            <div className="py-12 text-center font-mono text-xs text-[var(--rzp-ink-faint)]">
              No audit entries recorded for this payment yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}