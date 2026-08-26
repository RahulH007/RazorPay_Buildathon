/**
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 *
 * What the model read, and what it returned.
 *
 * Every row here is a ledger entry, shown with its sequence number and entry
 * hash. That is the point: the model's reasoning is not a log line that could
 * say anything - it is covered by the same hash chain as the spend, so a
 * reviewer can check that what the panel claims Gemini said is what the ledger
 * recorded at the time.
 */

import { useEffect, useState } from 'react';
import { Bot, GitBranch, ShieldBan, Link2, ChevronDown } from 'lucide-react';
import api from '../../utils/api';

// How each recorded action should read to someone who did not write the code.
const KINDS = {
  FAILURE_DIAGNOSED_LLM: {
    label: 'Diagnosed an unmapped error',
    tone: 'bg-violet-50 text-violet-700 border-violet-200',
    icon: Bot,
  },
  CUSTOMER_REPLY_PARSED: {
    label: 'Read a customer reply',
    tone: 'bg-blue-50 text-[var(--rzp-blue-600)] border-blue-200',
    icon: Bot,
  },
  PROMISE_TO_PAY_RECORDED: {
    label: 'Recorded a promise to pay',
    tone: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    icon: Bot,
  },
  ESCALATED_TO_HUMAN: {
    label: 'Escalated to a human',
    tone: 'bg-amber-50 text-amber-700 border-amber-200',
    icon: ShieldBan,
  },
  LLM_OUTPUT_REJECTED: {
    label: 'Output rejected by a guard',
    tone: 'bg-rose-50 text-rose-700 border-rose-200',
    icon: ShieldBan,
  },
  VOICE_SCRIPT_GENERATED: {
    label: 'Wrote a voice script',
    tone: 'bg-blue-50 text-[var(--rzp-blue-600)] border-blue-200',
    icon: Bot,
  },
  WHATSAPP_LINK_SENT: {
    label: 'Wrote a WhatsApp message',
    tone: 'bg-blue-50 text-[var(--rzp-blue-600)] border-blue-200',
    icon: Bot,
  },
};

function Row({ item }) {
  const [open, setOpen] = useState(false);
  const kind = KINDS[item.action] || {
    label: item.action,
    tone: 'bg-slate-50 text-slate-600 border-slate-200',
    icon: GitBranch,
  };
  const Icon = kind.icon;
  const long = (item.details || '').length > 150;

  return (
    <div className="border-b border-[var(--rzp-border)] px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${kind.tone}`}>
          <Icon size={11} strokeWidth={2.2} />
          {kind.label}
        </span>

        <span className="font-mono text-[11px] text-[var(--rzp-ink-faint)]">
          #{item.sequence_no}
        </span>

        <span className="font-mono text-[11px] text-[var(--rzp-ink-muted)]">
          {item.payment_id}
        </span>

        {item.confidence != null && (
          <span
            className={`rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold ${
              item.confidence >= 0.7
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-amber-200 bg-amber-50 text-amber-700'
            }`}
            title={item.confidence >= 0.7 ? 'At or above the 0.70 threshold' : 'Below the 0.70 threshold, so it escalates'}
          >
            {(item.confidence * 100).toFixed(0)}% confident
          </span>
        )}

        <span className="ml-auto flex items-center gap-2 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
          {item.model && <span>{item.model}</span>}
          {item.latency_ms != null && <span>{item.latency_ms}ms</span>}
          {item.input_tokens != null && (
            <span>{item.input_tokens}/{item.output_tokens} tok</span>
          )}
        </span>
      </div>

      <p
        className={`mt-2 text-xs leading-relaxed text-[var(--rzp-ink-muted)] ${
          open ? '' : 'line-clamp-2'
        }`}
      >
        {item.details}
      </p>

      <div className="mt-2 flex items-center gap-3">
        {long && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="inline-flex cursor-pointer items-center gap-1 text-[11px] font-semibold text-[var(--rzp-blue-600)] hover:text-[var(--rzp-blue-700)]"
          >
            {open ? 'Show less' : 'Show more'}
            <ChevronDown
              size={11}
              strokeWidth={2.5}
              className={open ? 'rotate-180 transition-transform' : 'transition-transform'}
            />
          </button>
        )}
        {item.entry_hash && (
          <span
            className="inline-flex items-center gap-1 font-mono text-[10px] text-[var(--rzp-ink-faint)]"
            title={`entry hash: ${item.entry_hash}`}
          >
            <Link2 size={10} strokeWidth={2} />
            {item.entry_hash.slice(0, 12)}…
          </span>
        )}
      </div>
    </div>
  );
}

export default function ModelInterpretations({ refreshKey }) {
  const [activity, setActivity] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getLlmActivity()
      .then((data) => { if (!cancelled) setActivity(data); })
      .catch(() => { if (!cancelled) setActivity(null); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const items = activity?.interpretations || [];

  return (
    <section className="rzp-card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-[var(--rzp-ink)]">
          <Bot size={15} strokeWidth={2} className="text-violet-600" />
          What the model read
        </h2>
        <span className="font-mono text-[11px] text-[var(--rzp-ink-faint)]">
          {items.length > 0
            ? `${items.length} most recent · every row is a ledger entry`
            : 'ledger entries, newest first'}
        </span>
      </div>

      {items.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="text-xs text-[var(--rzp-ink-muted)]">
            Nothing recorded yet for this batch.
          </p>
          <p className="mt-1 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
            Run a batch, or populate the response cache with{' '}
            <span className="text-[var(--rzp-ink-muted)]">make refresh-llm-cache</span>
          </p>
        </div>
      ) : (
        <div className="max-h-[420px] overflow-y-auto custom-scrollbar">
          {items.map((item) => (
            <Row key={item.sequence_no} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}
