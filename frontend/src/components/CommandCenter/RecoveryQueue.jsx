/**
 * RecoverOS — Recovery queue
 *
 * The working list. Filters by pipeline stage (driven from the pipeline
 * above), by failure class, and by a free-text match on customer or payment
 * id. Sorted by amount so the money at risk is what a reviewer sees first.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useMemo, useState } from 'react';
import { ListFilter, Loader2, Search, X } from 'lucide-react';

import QueueCard from './QueueCard';
import { OUTCOME_BUCKETS, outcomeBucket } from '../../utils/decisions';

const CLASS_FILTERS = [
  { key: 'ALL', label: 'All' },
  { key: 'TRANSIENT_TECHNICAL', label: 'Transient' },
  { key: 'AUTH_FRICTION', label: 'Auth' },
  { key: 'MANDATE_BALANCE', label: 'Mandate' },
  { key: 'B2B_RECEIVABLE', label: 'B2B' },
  { key: 'HARD_DECLINE', label: 'Hard decline' },
];

const STAGE_LABEL = Object.fromEntries(
  Object.values(OUTCOME_BUCKETS).map((b) => [b.key, b.label])
);

export default function RecoveryQueue({
  records = [],
  decisions = {},
  selectedId,
  processingId,
  onSelect,
  stageFilter,
  onClearStage,
  index,
}) {
  const [classFilter, setClassFilter] = useState('ALL');
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    return records
      .filter((r) => {
        if (classFilter !== 'ALL' && r.failure_class !== classFilter) return false;

        // The filter comes from the outcome bar above, so it must be read
        // through the same bucketing the bar used — matching on
        // recovery_state instead would put a holdout control under "stopped"
        // and disagree with the width the reviewer just clicked.
        if (stageFilter && outcomeBucket(r, decisions[r.payment_id]).key !== stageFilter) {
          return false;
        }

        if (q) {
          // error_reason is on the card now, so it must be searchable —
          // typing what you can see and getting nothing reads as broken.
          const haystack = `${r.payment_id} ${r.customer_name || ''} ${r.error_reason || ''}`
            .toLowerCase();
          if (!haystack.includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => (b.amount || 0) - (a.amount || 0));
  }, [records, decisions, classFilter, stageFilter, query]);

  return (
    <section className="rzp-card flex min-h-0 flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-[var(--rzp-ink)]">
            <ListFilter size={14} strokeWidth={2.2} className="text-[var(--rzp-blue-600)]" />
            Recovery queue
          </h2>
          <span className="font-mono text-[11px] text-[var(--rzp-ink-faint)]">
            {filtered.length} of {records.length}
          </span>
        </div>

        {/* Search */}
        <div className="relative mt-2.5">
          <Search
            size={13}
            strokeWidth={2.2}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--rzp-ink-faint)]"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Customer, payment id or error reason…"
            className="w-full rounded-lg border border-[var(--rzp-border)] bg-white py-1.5 pl-8 pr-3 font-mono text-xs text-[var(--rzp-ink)] outline-none transition-colors placeholder:text-[var(--rzp-ink-faint)] focus:border-[var(--rzp-blue-600)]"
          />
        </div>

        {/* Class chips */}
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {CLASS_FILTERS.map(({ key, label }) => {
            const count =
              key === 'ALL'
                ? records.length
                : records.filter((r) => r.failure_class === key).length;
            const active = classFilter === key;
            return (
              <button
                key={key}
                onClick={() => setClassFilter(key)}
                className={`cursor-pointer rounded-md border px-2 py-1 text-[10px] font-bold transition-colors ${
                  active
                    ? 'border-[var(--rzp-blue-600)] bg-[var(--rzp-blue-050)] text-[var(--rzp-blue-600)]'
                    : 'border-[var(--rzp-border)] bg-white text-[var(--rzp-ink-muted)] hover:border-[var(--rzp-border-strong)]'
                }`}
              >
                {label}
                <span className="ml-1 font-mono text-[9px] text-[var(--rzp-ink-faint)]">{count}</span>
              </button>
            );
          })}
        </div>

        {/* Active stage filter, cleared from here rather than from the pipeline */}
        {stageFilter && (
          <button
            onClick={onClearStage}
            className="mt-2.5 inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-[var(--rzp-blue-600)] bg-[var(--rzp-blue-050)] px-2 py-1 font-mono text-[10px] font-bold text-[var(--rzp-blue-600)]"
          >
            showing: {STAGE_LABEL[stageFilter] || stageFilter.toLowerCase()}
            <X size={10} strokeWidth={2.6} />
          </button>
        )}

        {/* Reading the ledger takes a moment on a large batch; say so rather
            than showing an empty "why" column that looks like missing data. */}
        {index?.isLoading && (
          <div className="mt-2.5 flex items-center gap-1.5 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
            <Loader2 size={10} strokeWidth={2.4} className="animate-spin" />
            reading decisions from the ledger — {index.loaded}/{index.total}
          </div>
        )}
      </div>

      {/* List */}
      <div className="custom-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <div className="flex h-32 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 p-4 text-center">
            <span className="font-mono text-[11px] italic text-[#94A3B8]">
              {records.length === 0 ? 'No records — run a batch' : 'No records match these filters'}
            </span>
          </div>
        ) : (
          filtered.map((record) => (
            <QueueCard
              key={record.payment_id}
              record={record}
              decision={decisions[record.payment_id]}
              isSelected={record.payment_id === selectedId}
              isProcessing={record.payment_id === processingId}
              onClick={() => onSelect(record)}
            />
          ))
        )}
      </div>
    </section>
  );
}
