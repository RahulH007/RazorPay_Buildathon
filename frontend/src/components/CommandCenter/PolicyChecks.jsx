/**
 * RecoverOS — Policy checks
 *
 * The gates in policy.py, in the order policy.py evaluates them, with the one
 * that fired marked.
 *
 * Order is the point. Checks run cheapest-first and the first refusal wins,
 * so gates below the one that fired are shown as never evaluated rather than
 * as passed — claiming they passed would misdescribe how the engine reaches
 * its answer. Every figure beside a gate is parsed out of the ledger entry
 * that recorded the decision, never recomputed in the browser.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { Check, Minus, X } from 'lucide-react';

import { buildPolicyChecks } from '../../utils/decisions';

const STATUS = {
  passed: {
    icon: Check,
    iconCls: 'border-emerald-200 bg-emerald-50 text-emerald-600',
    rowCls: 'border-[var(--rzp-border)] bg-white',
    labelCls: 'text-[var(--rzp-ink)]',
  },
  fired: {
    icon: X,
    iconCls: 'border-amber-300 bg-amber-100 text-amber-700',
    rowCls: 'border-amber-300 bg-amber-50',
    labelCls: 'text-amber-900 font-bold',
  },
  skipped: {
    icon: Minus,
    iconCls: 'border-slate-200 bg-slate-50 text-slate-400',
    rowCls: 'border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] opacity-60',
    labelCls: 'text-[var(--rzp-ink-faint)]',
  },
};

/** A ratio bar for the cost ceiling — the one gate with a meaningful scale. */
function CeilingBar({ policy, spendPaise }) {
  const ceiling = policy?.ceilingPaise;
  if (!ceiling) return null;
  const spent = policy.spentAfterPaise ?? spendPaise ?? 0;
  const pct = Math.min(100, (spent / ceiling) * 100);

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--rzp-surface-sunken)]">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            pct >= 100 ? 'bg-rose-500' : 'bg-[var(--rzp-blue-600)]'
          }`}
          style={{ width: `${Math.max(pct, 1)}%` }}
        />
      </div>
      <span className="shrink-0 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
        {pct < 1 ? '<1' : pct.toFixed(0)}%
      </span>
    </div>
  );
}

export default function PolicyChecks({ decision }) {
  const checks = buildPolicyChecks(decision);
  if (checks.length === 0) return null;

  const neverEvaluated = checks.every((g) => g.status === 'skipped');

  return (
    <div className="space-y-1.5">
      {neverEvaluated && (
        <p className="rounded-lg border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-2.5 py-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
          This record was held before it reached the policy engine, so none of
          these gates were evaluated. They are shown greyed rather than passed.
        </p>
      )}
      {checks.map((gate) => {
        const s = STATUS[gate.status];
        const Icon = s.icon;
        return (
          <div key={gate.id} className={`flex items-start gap-2.5 rounded-lg border p-2.5 ${s.rowCls}`}>
            <span
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${s.iconCls}`}
            >
              <Icon size={11} strokeWidth={2.8} />
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className={`text-xs ${s.labelCls}`}>{gate.label}</span>
                {gate.detail && (
                  <span className="font-mono text-[10px] text-[var(--rzp-ink-muted)]">
                    {gate.detail}
                  </span>
                )}
              </div>

              {gate.id === 'cac' && gate.status !== 'skipped' && (
                <CeilingBar policy={decision.policy} spendPaise={decision.spendPaise} />
              )}

              {gate.status === 'fired' && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-amber-900">
                  {decision.reasonText}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
