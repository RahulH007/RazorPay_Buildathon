import {
  Server,
  GitBranch,
  Sparkles,
  UserRound,
  Banknote,
  Bot,
  Zap,
  Target,
  Link2,
  ShieldBan,
} from 'lucide-react';

const ACTOR = {
  system: { icon: Server, cls: 'bg-slate-100 text-slate-600', label: 'system' },
  rule_engine: { icon: GitBranch, cls: 'bg-[#EEF4FF] text-[#2B6DEF]', label: 'rule engine' },
  llm_agent: { icon: Sparkles, cls: 'bg-violet-50 text-violet-600', label: 'llm agent' },
  policy_engine: { icon: ShieldBan, cls: 'bg-amber-50 text-amber-600', label: 'policy engine' },
  outcome_engine: { icon: Target, cls: 'bg-[#ECFDF3] text-[#039855]', label: 'outcome engine' },
  customer: { icon: UserRound, cls: 'bg-amber-50 text-amber-700', label: 'customer' },
};

const chip =
  'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px]';

export default function AuditEntry({ entry, isHardDecline }) {
  const actor = ACTOR[entry.actor] || ACTOR.system;
  const ActorIcon = actor.icon;

  // A refusal is a first-class outcome here, so it gets its own treatment
  // rather than being styled as an error.
  const isRefusal =
    isHardDecline ||
    entry.action?.startsWith('POLICY_DECLINED') ||
    entry.action?.includes('SUPPRESSED') ||
    entry.action?.includes('WHY_WE_DIDNT_ACT');

  const costInr = entry.cost_inr ?? (entry.cost_paise ?? 0) / 100;
  const cumulativeInr =
    entry.cumulative_cost_inr ?? (entry.cumulative_cost_paise ?? 0) / 100;

  return (
    <div
      className={`flex gap-3 rounded-xl border p-3 transition-colors duration-200 ${
        isRefusal
          ? 'border-amber-200 bg-amber-50/60'
          : 'border-[var(--rzp-border)] bg-white hover:border-[var(--rzp-border-strong)]'
      }`}
    >
      {/* Actor chip */}
      <span
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${actor.cls}`}
        title={actor.label}
      >
        <ActorIcon size={13} strokeWidth={2} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="flex items-baseline gap-2 font-mono text-[11px] font-bold tracking-tight text-[var(--rzp-ink)]">
            {entry.sequence_no != null && (
              <span className="text-[var(--rzp-ink-faint)]">#{entry.sequence_no}</span>
            )}
            <span>{entry.action}</span>
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

        <p className="mt-1 break-words text-xs leading-relaxed text-[var(--rzp-ink-muted)]">
          {entry.details}
        </p>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {/* The hash is the point of this panel: it is what makes the row
              checkable rather than merely readable. */}
          {entry.entry_hash && (
            <span
              className={`${chip} bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-muted)]`}
              title={`entry hash: ${entry.entry_hash}`}
            >
              <Link2 size={10} strokeWidth={2} />
              {entry.entry_hash.slice(0, 12)}…
            </span>
          )}

          {costInr > 0 && (
            <span className={`${chip} bg-[#ECFDF3] text-[#039855]`}>
              <Banknote size={10} strokeWidth={2} />
              ₹{costInr.toFixed(2)}
            </span>
          )}

          {cumulativeInr > 0 && (
            <span className={`${chip} bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-muted)]`}>
              Σ ₹{cumulativeInr.toFixed(2)}
            </span>
          )}

          {entry.llm_metadata && (
            <>
              <span className={`${chip} bg-violet-50 text-violet-700`}>
                <Bot size={10} strokeWidth={2} />
                {entry.llm_metadata.model}
              </span>
              {entry.llm_metadata.latency_ms != null && (
                <span className={`${chip} bg-[#EEF4FF] text-[var(--rzp-blue-600)]`}>
                  <Zap size={10} strokeWidth={2} />
                  {entry.llm_metadata.latency_ms}ms
                </span>
              )}
              {entry.llm_metadata.confidence != null && (
                <span className={`${chip} bg-[#EEF4FF] text-[var(--rzp-blue-600)]`}>
                  <Target size={10} strokeWidth={2} />
                  {(entry.llm_metadata.confidence * 100).toFixed(0)}%
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
