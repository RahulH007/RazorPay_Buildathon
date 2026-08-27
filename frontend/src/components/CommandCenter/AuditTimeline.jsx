/**
 * RecoverOS — Audit timeline
 *
 * The current run's ledger entries, in chain order, with the hash that makes
 * each row checkable rather than merely readable.
 *
 * Earlier runs are collapsed by default. The same payment id is re-ingested
 * by every batch, so one trail can hold seven runs; flattening them into a
 * single list reads as one incoherent story where a record is diagnosed four
 * times and stopped three.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useState } from 'react';
import {
  Banknote,
  Bot,
  ChevronDown,
  GitBranch,
  History,
  Link2,
  Server,
  ShieldBan,
  Sparkles,
  Target,
  UserRound,
  Zap,
} from 'lucide-react';

const ACTOR = {
  system: { icon: Server, cls: 'bg-slate-100 text-slate-600' },
  rule_engine: { icon: GitBranch, cls: 'bg-[#EEF4FF] text-[#2B6DEF]' },
  llm_agent: { icon: Sparkles, cls: 'bg-violet-50 text-violet-600' },
  policy_engine: { icon: ShieldBan, cls: 'bg-amber-50 text-amber-600' },
  outcome_engine: { icon: Target, cls: 'bg-[#ECFDF3] text-[#039855]' },
  customer: { icon: UserRound, cls: 'bg-amber-50 text-amber-700' },
};

const chip = 'inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]';

function Entry({ entry, isLast }) {
  const actor = ACTOR[entry.actor] || ACTOR.system;
  const ActorIcon = actor.icon;

  const isRefusal =
    entry.action?.startsWith('POLICY_DECLINED')
    || entry.action?.includes('SUPPRESSED')
    || entry.action?.includes('WHY_WE_DIDNT_ACT')
    || entry.action?.includes('HELD')
    || entry.action?.includes('BLOCKED');

  const isWin = entry.action?.endsWith('_TO_RECOVERED');
  const cost = entry.cost_paise || 0;

  return (
    <li className="relative flex gap-3 pb-3 last:pb-0">
      {/* Chain rail — the visual analogue of prev_hash */}
      {!isLast && (
        <span className="absolute left-[13px] top-7 bottom-0 w-px bg-[var(--rzp-border)]" />
      )}

      <span
        className={`relative z-10 mt-0.5 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-lg ring-4 ring-white ${actor.cls}`}
        title={entry.actor}
      >
        <ActorIcon size={12} strokeWidth={2} />
      </span>

      <div
        className={`min-w-0 flex-1 rounded-lg border p-2.5 ${
          isRefusal
            ? 'border-amber-200 bg-amber-50/60'
            : isWin
            ? 'border-emerald-200 bg-emerald-50/50'
            : 'border-[var(--rzp-border)] bg-white'
        }`}
      >
        <div className="flex items-baseline justify-between gap-2">
          <span className="flex min-w-0 items-baseline gap-1.5 font-mono text-[11px] font-bold tracking-tight text-[var(--rzp-ink)]">
            <span className="shrink-0 text-[var(--rzp-ink-faint)]">#{entry.sequence_no}</span>
            <span className="truncate">{entry.action}</span>
          </span>
          <span className="shrink-0 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
            {entry.timestamp
              ? new Date(entry.timestamp).toLocaleTimeString('en-IN', {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                })
              : ''}
          </span>
        </div>

        <p className="mt-1 break-words text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
          {entry.details}
        </p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {entry.entry_hash && (
            <span
              className={`${chip} bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-muted)]`}
              title={`entry hash: ${entry.entry_hash}\nprev hash: ${entry.prev_hash || '—'}`}
            >
              <Link2 size={9} strokeWidth={2} />
              {entry.entry_hash.slice(0, 10)}…
            </span>
          )}

          {cost > 0 && (
            <span className={`${chip} bg-[#ECFDF3] text-[#039855]`}>
              <Banknote size={9} strokeWidth={2} />
              ₹{(cost / 100).toFixed(2)}
            </span>
          )}

          {entry.llm_metadata && (
            <>
              <span className={`${chip} bg-violet-50 text-violet-700`}>
                <Bot size={9} strokeWidth={2} />
                {entry.llm_metadata.model}
              </span>
              {entry.llm_metadata.latency_ms != null && (
                <span className={`${chip} bg-[#EEF4FF] text-[var(--rzp-blue-600)]`}>
                  <Zap size={9} strokeWidth={2} />
                  {entry.llm_metadata.latency_ms}ms
                </span>
              )}
              {entry.llm_metadata.confidence != null && (
                <span className={`${chip} bg-[#EEF4FF] text-[var(--rzp-blue-600)]`}>
                  <Target size={9} strokeWidth={2} />
                  {(entry.llm_metadata.confidence * 100).toFixed(0)}%
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </li>
  );
}

export default function AuditTimeline({ decision }) {
  const [showEarlier, setShowEarlier] = useState(false);
  if (!decision) return null;

  const { run, earlier, earlierRunCount } = decision;
  const shown = showEarlier ? [...earlier, ...run] : run;

  return (
    <div>
      {earlier.length > 0 && (
        <button
          onClick={() => setShowEarlier((v) => !v)}
          className="mb-3 inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-2.5 py-1.5 font-mono text-[10px] font-semibold text-[var(--rzp-ink-muted)] transition-colors hover:border-[var(--rzp-border-strong)]"
        >
          <History size={11} strokeWidth={2.2} />
          {showEarlier ? 'Hide' : 'Show'} {earlier.length} entries from{' '}
          {earlierRunCount} earlier {earlierRunCount === 1 ? 'run' : 'runs'}
          <ChevronDown
            size={11}
            strokeWidth={2.5}
            className={showEarlier ? 'rotate-180 transition-transform' : 'transition-transform'}
          />
        </button>
      )}

      <ol className="relative">
        {shown.map((entry, i) => (
          <Entry key={entry.sequence_no} entry={entry} isLast={i === shown.length - 1} />
        ))}
      </ol>
    </div>
  );
}
