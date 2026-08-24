import {
  Server,
  GitBranch,
  Sparkles,
  UserRound,
  Banknote,
  Bot,
  Zap,
  Target,
} from 'lucide-react';

const ACTOR = {
  system: { icon: Server, cls: 'bg-slate-400/10 text-slate-300 border-slate-400/20', label: 'system' },
  rule_engine: { icon: GitBranch, cls: 'bg-blue-500/10 text-blue-300 border-blue-400/20', label: 'rule engine' },
  llm_agent: { icon: Sparkles, cls: 'border-violet-400/20 bg-violet-500/10 text-violet-300', label: 'llm agent' },
  customer: { icon: UserRound, cls: 'bg-amber-500/10 text-amber-300 border-amber-400/20', label: 'customer' },
};

export default function AuditEntry({ entry, isHardDecline }) {
  const actor = ACTOR[entry.actor] || ACTOR.system;
  const ActorIcon = actor.icon;

  return (
    <div
      className={`flex gap-3 rounded-xl border p-3 transition-colors duration-200 ${
        isHardDecline
          ? 'border-red-400/15 bg-red-400/[0.04]'
          : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12]'
      }`}
    >
      {/* Actor chip */}
      <span
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${actor.cls}`}
        title={actor.label}
      >
        <ActorIcon size={13} strokeWidth={2} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-[11px] font-bold tracking-tight text-slate-100">
            {entry.action}
          </span>
          <span className="shrink-0 font-mono text-[10px] text-slate-500">
            {entry.timestamp
              ? new Date(entry.timestamp).toLocaleTimeString('en-IN', {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                })
              : ''}
          </span>
        </div>

        <p className="mt-1 break-words text-xs leading-relaxed text-slate-400">{entry.details}</p>

        {(entry.cost_incurred_inr > 0 ||
          entry.cumulative_cost_inr > 0 ||
          entry.llm_metadata) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {entry.cost_incurred_inr > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-400/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
                <Banknote size={10} strokeWidth={2} />
                ₹{Number(entry.cost_incurred_inr).toFixed(2)}
              </span>
            )}
            {entry.cumulative_cost_inr > 0 && (
              <span className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                Σ ₹{Number(entry.cumulative_cost_inr).toFixed(2)}
              </span>
            )}
            {entry.llm_metadata && (
              <>
                <span className="inline-flex items-center gap-1 rounded-md bg-violet-400/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-violet-300">
                  <Bot size={10} strokeWidth={2} />
                  {entry.llm_metadata.model}
                </span>
                {entry.llm_metadata.latency_ms && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-cyan-400/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                    <Zap size={10} strokeWidth={2} />
                    {entry.llm_metadata.latency_ms}ms
                  </span>
                )}
                {entry.llm_metadata.confidence != null && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-blue-400/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-blue-300">
                    <Target size={10} strokeWidth={2} />
                    {(entry.llm_metadata.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
