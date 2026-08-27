/**
 * RecoverOS — Recovery queue card
 *
 * Four questions, four lines, in the order a reviewer asks them:
 *
 *   How much money?          the amount, largest type on the card
 *   Why did it fail?         the gateway's error reason → the class we mapped it to
 *   What did RecoverOS do?   the policy verdict, by reason code
 *   What happened?           the outcome bucket, and what it cost to get there
 *
 * The decision chip is the load-bearing one. It shows the reason code rather
 * than the state, because "FAILED_STOPPED" answers where a record ended and
 * not why — and why is the entire claim this product makes.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import {
  ArrowRight,
  CalendarClock,
  CircleCheck,
  MessageCircle,
  PauseCircle,
  PhoneCall,
  RefreshCcw,
  ShieldCheck,
  Zap,
} from 'lucide-react';

import { formatCurrency, formatTimeAgo, truncateId } from '../../utils/formatters';
import { outcomeBucket, reasonMeta } from '../../utils/decisions';

const CLASS_BADGE = {
  TRANSIENT_TECHNICAL: { cls: 'bg-blue-50 text-[var(--rzp-blue-600)] border-blue-200', bar: 'bg-[var(--rzp-blue-600)]', label: 'Transient' },
  AUTH_FRICTION: { cls: 'bg-amber-50 text-amber-700 border-amber-200', bar: 'bg-amber-500', label: 'Auth Friction' },
  MANDATE_BALANCE: { cls: 'bg-violet-50 text-violet-700 border-violet-200', bar: 'bg-violet-500', label: 'Mandate' },
  B2B_RECEIVABLE: { cls: 'bg-teal-50 text-teal-700 border-teal-200', bar: 'bg-teal-500', label: 'B2B Invoice' },
  HARD_DECLINE: { cls: 'bg-rose-50 text-rose-700 border-rose-200', bar: 'bg-rose-500', label: 'Hard Decline' },
};

// Outcome tones mirror the bar in the pipeline above, so a card and the slice
// it belongs to are recognisably the same colour.
const OUTCOME = {
  RECOVERED: { icon: CircleCheck, cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', accent: 'bg-emerald-500' },
  IN_PROGRESS: { icon: Zap, cls: 'border-amber-200 bg-amber-50 text-amber-700', accent: 'bg-amber-500' },
  HELD: { icon: PauseCircle, cls: 'border-violet-200 bg-violet-50 text-violet-700', accent: 'bg-violet-500' },
  STOPPED: { icon: ShieldCheck, cls: 'border-slate-200 bg-slate-100 text-slate-700', accent: 'bg-slate-400' },
};

const CHANNEL = {
  WHATSAPP_LINK_SENT: { icon: MessageCircle, label: 'WhatsApp link sent' },
  RETRY_SILENT_ATTEMPT: { icon: RefreshCcw, label: 'Silent retry' },
  MANDATE_RESEQUENCED: { icon: CalendarClock, label: 'Mandate resequenced' },
  VOICE_CALL_INITIATED: { icon: PhoneCall, label: 'Voice call placed' },
};

export default function QueueCard({ record, decision, isSelected, isProcessing, onClick }) {
  const badge = CLASS_BADGE[record.failure_class];
  const bucket = outcomeBucket(record, decision);
  const outcome = OUTCOME[bucket.key];
  const OutcomeIcon = outcome.icon;
  const meta = decision ? reasonMeta(decision.reasonCode) : null;
  const channel = decision?.action ? CHANNEL[decision.action.channel] : null;
  const ChannelIcon = channel?.icon;

  return (
    <button
      onClick={onClick}
      className={`group relative w-full cursor-pointer overflow-hidden rounded-xl border p-3 text-left transition-all duration-200 ease-out hover:-translate-y-0.5 ${
        isSelected
          ? 'border-blue-400 bg-blue-50 shadow-md ring-1 ring-blue-300'
          : isProcessing
          ? 'border-blue-300 bg-blue-50/50 shadow-sm'
          : 'border-slate-200 bg-white shadow-xs hover:border-blue-300 hover:bg-blue-50/30'
      }`}
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${outcome.accent}`} />

      {isProcessing && (
        <span className="absolute right-2 top-2 h-2 w-2 animate-ping rounded-full bg-[var(--rzp-blue-600)]" />
      )}

      {/* 1 · How much money — and what happened to it */}
      <div className="flex items-center justify-between gap-2 pl-1.5">
        <span className="font-mono text-base font-extrabold tracking-tight text-[var(--rzp-ink)]">
          {formatCurrency(record.amount)}
        </span>
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${outcome.cls}`}
        >
          <OutcomeIcon size={9} strokeWidth={2.6} />
          {bucket.label}
        </span>
      </div>

      {/* Who */}
      <div className="mt-0.5 flex items-baseline gap-2 pl-1.5">
        <span className="truncate text-xs font-semibold text-[var(--rzp-ink)]">
          {record.customer_name}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
          {truncateId(record.payment_id)}
        </span>
        {decision?.lastTimestamp && (
          <span className="ml-auto shrink-0 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
            {formatTimeAgo(decision.lastTimestamp)}
          </span>
        )}
      </div>

      {/* 2 · Why it failed — the gateway's word, then ours */}
      <div className="mt-2 flex items-center gap-1.5 pl-1.5">
        <span
          className="truncate font-mono text-[10px] text-[var(--rzp-ink-muted)]"
          title={record.error_description || record.error_reason}
        >
          {record.error_reason || 'unknown error'}
        </span>
        <ArrowRight size={9} strokeWidth={2.6} className="shrink-0 text-[var(--rzp-ink-faint)]" />
        {badge ? (
          <span
            className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${badge.cls}`}
          >
            {badge.label}
          </span>
        ) : (
          <span className="shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[9px] text-[#94A3B8]">
            Diagnosing…
          </span>
        )}
      </div>

      {/* 3 · What RecoverOS decided, and 4 · what it cost */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-dashed border-[var(--rzp-border)] pt-2 pl-1.5">
        {meta ? (
          <span
            className="truncate text-[11px] font-bold text-[var(--rzp-ink)]"
            title={decision.reasonText || meta.label}
          >
            {meta.headline || meta.label}
          </span>
        ) : (
          <span className="font-mono text-[10px] italic text-[var(--rzp-ink-faint)]">
            reading decision…
          </span>
        )}

        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {decision?.confidence != null && (
            <span
              className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${
                decision.confidence >= 0.7
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : 'border-amber-200 bg-amber-50 text-amber-700'
              }`}
              title={
                decision.confidence >= 0.7
                  ? 'At or above the 0.70 confidence threshold'
                  : 'Below the 0.70 threshold, so it escalates'
              }
            >
              {(decision.confidence * 100).toFixed(0)}%
            </span>
          )}

          {decision && (
            <span
              className="inline-flex items-center gap-1 rounded border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-1.5 py-0.5 font-mono text-[9px] text-[var(--rzp-ink-muted)]"
              title={channel ? channel.label : 'no customer contact was made'}
            >
              {ChannelIcon && <ChannelIcon size={9} strokeWidth={2.2} />}
              ₹{decision.spendInr.toFixed(2)}
            </span>
          )}
        </span>
      </div>
    </button>
  );
}
