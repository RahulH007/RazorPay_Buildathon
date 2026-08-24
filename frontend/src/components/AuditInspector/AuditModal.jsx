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
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#02042B]/85 p-4 backdrop-blur-md animate-overlay-in"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-white/[0.12] bg-[#071026] shadow-2xl shadow-black/80 animate-modal-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-white/[0.08] px-6 py-4 bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 text-cyan-300">
              <Search size={16} strokeWidth={2.2} />
            </span>
            <div>
              <div className="text-base font-bold text-white flex items-center gap-2">
                <span>Cryptographic Audit Inspector</span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                  Immutable Log
                </span>
              </div>
              <div className="font-mono text-xs text-slate-400 mt-0.5">{record.payment_id}</div>
            </div>
          </div>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-400 transition-all hover:border-white/20 hover:text-white"
            onClick={onClose}
            aria-label="Close audit inspector"
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {/* Summary chips */}
        <div className="flex shrink-0 flex-wrap gap-2 border-b border-white/[0.06] px-6 py-3 bg-[#02042B]/40">
          {summary.map(({ label, value }) => (
            <span
              key={label}
              className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-1.5"
            >
              <span className="mr-2 text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">
                {label}
              </span>
              <span className="font-mono text-xs font-semibold text-white">{value}</span>
            </span>
          ))}
          {auditData && (
            <span className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
              <span className="mr-2 text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-400">
                Total Spend
              </span>
              <span className="font-mono text-xs font-bold text-emerald-300">
                ₹{auditData.total_cost_inr?.toFixed(2) || '0.00'}
              </span>
            </span>
          )}
        </div>

        {/* Timeline */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4 space-y-2 custom-scrollbar">
          {loading ? (
            <div className="py-12 text-center text-xs font-mono text-slate-400 flex flex-col items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
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
            <div className="py-12 text-center text-xs font-mono text-slate-500">
              No audit entries recorded for this payment yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}