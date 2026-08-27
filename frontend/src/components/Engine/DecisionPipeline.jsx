/**
 * RecoverOS — Decision pipeline
 *
 * The six stages a failed payment passes through, each shown twice: how the
 * stage works, and what it did to one real record.
 *
 * The left column is documentation — it describes mechanism, and every claim
 * in it is traceable to a file in this repository. The right column is
 * evidence, read out of that record's hash-chained ledger entries. Keeping
 * them visibly separate is the point: a reader can tell at a glance which
 * half is the pitch and which half is the receipt.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import {
  AlertCircle,
  ArrowRight,
  Bot,
  Check,
  CircleCheck,
  GitBranch,
  Layers,
  Link2,
  Minus,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';

import { buildPolicyChecks, reasonMeta } from '../../utils/decisions';
import { formatCurrencyFull } from '../../utils/formatters';

const CHANNEL_LABEL = {
  WHATSAPP_LINK_SENT: 'WhatsApp payment link',
  RETRY_SILENT_ATTEMPT: 'Silent retry',
  MANDATE_RESEQUENCED: 'UPI mandate re-sequence',
  VOICE_CALL_INITIATED: 'Hinglish voice call',
};

const STAGES = [
  {
    key: 'failed',
    n: 1,
    label: 'Payment failed',
    icon: AlertCircle,
    tone: 'rose',
    source: 'routes/webhooks.py · event_adapter.py',
    how: [
      'A payment.failed webhook arrives from Razorpay. Its HMAC-SHA256 signature is verified over the exact bytes received, and outside demo mode an unsigned or mis-signed webhook is refused rather than trusted.',
      'The event is normalised and written to the ledger as RECORD_INGESTED before anything acts on it, so the trail starts at arrival rather than at the first decision.',
    ],
  },
  {
    key: 'diagnose',
    n: 2,
    label: 'Diagnose',
    icon: GitBranch,
    tone: 'blue',
    source: 'classifier.py · llm_agent.py',
    how: [
      'The rule engine matches error.reason against a fixed map first. That path is deterministic, costs nothing and calls no model — and it handles the large majority of traffic.',
      'Only a code the rules do not recognise is sent to Gemini, which returns a structured root cause with a confidence score. Below the 0.70 threshold the record escalates to a human instead of being guessed at.',
    ],
  },
  {
    key: 'classify',
    n: 3,
    label: 'Classify',
    icon: Layers,
    tone: 'violet',
    source: 'classifier.py',
    how: [
      'Every record lands in exactly one of five failure classes: transient technical, auth friction, mandate or balance, B2B receivable, hard decline.',
      'The class is not a label for reporting — it selects the escalation ladder, which decides what may be tried and in what order.',
    ],
  },
  {
    key: 'policy',
    n: 4,
    label: 'Policy gates',
    icon: ShieldCheck,
    tone: 'amber',
    source: 'policy.py · guardrails.py · consent.py',
    how: [
      'The gates run cheapest-first and the first refusal wins, so the recorded reason is the most fundamental one rather than whichever was evaluated last.',
      'Nine reason codes cover every outcome, refusals included. Restraint is an output of this system, not an absence of one, so a refusal is written to the ledger exactly as an action is.',
    ],
  },
  {
    key: 'action',
    n: 5,
    label: 'Choose action',
    icon: Send,
    tone: 'blue',
    source: 'recovery_actions.py · razorpay_client.py',
    how: [
      'The ladder for the class supplies the next channel, cheapest rung first: a silent retry costs nothing and is always tried before anything that reaches a person.',
      'Cost is charged in integer paise and accumulated per record, because the cost ceiling is evaluated against spend that has actually happened rather than against zero.',
    ],
  },
  {
    key: 'settlement',
    n: 6,
    label: 'Settlement',
    icon: CircleCheck,
    tone: 'emerald',
    source: 'settlement.py · models.py',
    how: [
      'A Razorpay Payment Link is correlated to the ledger entry that produced it, keyed by that entry hash — so the link is tied to the tamper-evident record of the action that created it.',
      'Settlement arrives on a signed payment_link.paid webhook and is applied exactly once; a replayed webhook settles nothing a second time.',
    ],
  },
];

const TONE = {
  rose: { dot: 'border-rose-300 bg-rose-100 text-rose-700', text: 'text-rose-700' },
  blue: { dot: 'border-blue-300 bg-blue-100 text-[var(--rzp-blue-600)]', text: 'text-[var(--rzp-blue-600)]' },
  violet: { dot: 'border-violet-300 bg-violet-100 text-violet-700', text: 'text-violet-700' },
  amber: { dot: 'border-amber-300 bg-amber-100 text-amber-700', text: 'text-amber-700' },
  emerald: { dot: 'border-emerald-300 bg-emerald-100 text-emerald-700', text: 'text-emerald-700' },
};

const HOLLOW = { dot: 'border-dashed border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-faint)]', text: 'text-[var(--rzp-ink-faint)]' };

function Fact({ label, value, mono = true, missing }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed border-[var(--rzp-border)] py-1.5 last:border-b-0">
      <span className="shrink-0 text-[11px] text-[var(--rzp-ink-muted)]">{label}</span>
      {value ? (
        <span className={`min-w-0 truncate text-[11px] font-semibold text-[var(--rzp-ink)] ${mono ? 'font-mono' : ''}`}>
          {value}
        </span>
      ) : (
        <span className="font-mono text-[11px] italic text-[var(--rzp-ink-faint)]">{missing || 'not recorded'}</span>
      )}
    </div>
  );
}

function EntryRef({ entry }) {
  if (!entry) return null;
  return (
    <p className="mt-2 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
      ledger #{entry.sequence_no} · {entry.entry_hash?.slice(0, 14)}…
    </p>
  );
}

/** The evidence half — what this stage actually did to the selected record. */
function Evidence({ stage, record, decision }) {
  const run = decision.run;
  const first = (pred) => run.find(pred) || null;
  const last = (pred) => { for (let i = run.length - 1; i >= 0; i -= 1) if (pred(run[i])) return run[i]; return null; };

  switch (stage.key) {
    case 'failed': {
      const e = first((x) => x.action === 'RECORD_INGESTED');
      return (
        <>
          <Fact label="error.reason" value={record.error_reason} />
          <Fact label="Amount" value={formatCurrencyFull(record.amount)} />
          <Fact label="Method" value={record.method} />
          <Fact label="Original payment ID" value={record.payment_id} />
          {record.error_description && (
            <p className="mt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
              gateway said: {record.error_description}
            </p>
          )}
          <EntryRef entry={e} />
        </>
      );
    }

    case 'diagnose': {
      const isModel = decision.diagnosis?.actor === 'llm_agent';
      const e = last((x) => x.action === 'FAILURE_DIAGNOSED_LLM') || last((x) => x.action.startsWith('CLASSIFIED_'));
      return (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold ${
                isModel
                  ? 'border-violet-200 bg-violet-50 text-violet-700'
                  : 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)]'
              }`}
            >
              {isModel ? <Bot size={10} strokeWidth={2.4} /> : <GitBranch size={10} strokeWidth={2.4} />}
              {isModel ? 'AI diagnosis' : 'Deterministic rule'}
            </span>
            {decision.confidence != null && (
              <span
                className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold ${
                  decision.confidence >= 0.7
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-amber-200 bg-amber-50 text-amber-700'
                }`}
              >
                {(decision.confidence * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>
          <Fact label="Decided by" value={decision.diagnosis?.actor} />
          <Fact
            label="Model"
            value={decision.diagnosis?.llm?.model}
            missing="no model call — rules matched"
          />
          <Fact
            label="Latency"
            value={decision.diagnosis?.llm?.latency_ms != null ? `${decision.diagnosis.llm.latency_ms}ms` : null}
            missing="—"
          />
          {decision.diagnosis?.text && (
            <p className="mt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
              {decision.diagnosis.text}
            </p>
          )}
          <EntryRef entry={e} />
        </>
      );
    }

    case 'classify': {
      const e = last((x) => x.action.startsWith('CLASSIFIED_'));
      const ladder = decision.policy?.ladderSteps
        || (decision.policy?.channel ? [decision.policy.channel] : null);
      return (
        <>
          <Fact label="Failure class" value={decision.diagnosis?.failureClass || record.failure_class} />
          {/* policy.py writes "Attempt {attempts + 1} of {len(ladder)}", so the
              number parsed out of the ledger is already 1-based. Adding one
              here printed "step 2 of 2" for a record whose own ledger entry —
              and whose row in the Command Center — both said step 1 of 2. */}
          <Fact
            label={ladder && ladder.length > 1 ? 'Ladder for this class' : 'Channel for this step'}
            value={ladder ? ladder.join(' → ') : null}
            missing="no ladder — this class is never contacted"
          />
          <Fact
            label="Ladder position"
            value={
              decision.policy?.attempt != null && decision.policy?.ladderLength != null
                ? `step ${decision.policy.attempt} of ${decision.policy.ladderLength}`
                : null
            }
            missing="—"
          />
          <EntryRef entry={e} />
        </>
      );
    }

    case 'policy': {
      const gates = buildPolicyChecks(decision);
      const meta = reasonMeta(decision.reasonCode);
      const ICON = { passed: Check, fired: X, skipped: Minus };
      const CLS = {
        passed: 'border-emerald-200 bg-emerald-50 text-emerald-600',
        fired: 'border-amber-300 bg-amber-100 text-amber-700',
        skipped: 'border-slate-200 bg-slate-50 text-slate-400',
      };
      return (
        <>
          <div className="mb-2.5 space-y-1">
            {gates.map((g) => {
              const Icon = ICON[g.status];
              return (
                <div key={g.id} className="flex items-start gap-2">
                  <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${CLS[g.status]}`}>
                    <Icon size={9} strokeWidth={3} />
                  </span>
                  <span className={`flex-1 text-[11px] ${g.status === 'fired' ? 'font-bold text-amber-900' : g.status === 'skipped' ? 'text-[var(--rzp-ink-faint)]' : 'text-[var(--rzp-ink)]'}`}>
                    {g.label}
                  </span>
                  {g.detail && (
                    <span className="shrink-0 font-mono text-[10px] text-[var(--rzp-ink-muted)]">{g.detail}</span>
                  )}
                </div>
              );
            })}
          </div>
          <div
            className={`rounded-lg border p-2.5 ${
              decision.acted ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'
            }`}
          >
            <p className="text-[11px] font-bold text-[var(--rzp-ink)]">
              {meta.headline || meta.label}
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
              {decision.reasonText}
            </p>
          </div>
          <EntryRef entry={decision.reasonEntry} />
        </>
      );
    }

    case 'action': {
      if (!decision.action) {
        // "The gate above is the whole reason" is only true when a gate
        // actually refused. A record whose policy approved an attempt that was
        // never written — a run that ended mid-flight — would have had the
        // refusal narrative put in its mouth.
        const refused = !decision.acted;
        return (
          <div className="rounded-lg border border-dashed border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3">
            <p className="text-[12px] font-bold text-[var(--rzp-ink)]">No action taken</p>
            {/* Derived, not typed. The invariant (no action implies no spend)
                holds today, but printing a literal makes the panel unable to
                ever disagree with the ledger it is quoting. */}
            <p className="mt-1 font-mono text-[11px] text-[var(--rzp-ink-muted)]">
              ₹{decision.spendInr.toFixed(2)} spent · no customer was contacted
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
              {refused
                ? 'The gate above is the whole reason. Stopping here is the engine working, not failing.'
                : `Policy approved an attempt${decision.policy?.channel ? ` on ${decision.policy.channel}` : ''}, but no action entry was written in this run.`}
            </p>
          </div>
        );
      }
      return (
        <>
          <Fact
            label="Channel"
            value={CHANNEL_LABEL[decision.action.channel] || decision.action.channel}
            mono={false}
          />
          <Fact label="Cost charged" value={`₹${decision.spendInr.toFixed(2)}`} />
          <Fact label="Attempts this run" value={String(decision.action.attempts)} />
          <Fact label="Payment Link" value={decision.paymentLinkUrl} missing="no link issued" />
          {decision.rejections > 0 && (
            <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700">
              Output guard rejected {decision.rejections} generated{' '}
              {decision.rejections === 1 ? 'message' : 'messages'}; a fixed template was sent instead.
            </p>
          )}
          <EntryRef entry={decision.action.entry} />
        </>
      );
    }

    case 'settlement': {
      const settled = last((x) => x.action.endsWith('_TO_RECOVERED'));
      if (!settled) {
        return (
          <div className="rounded-lg border border-dashed border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3">
            <p className="text-[12px] font-bold text-[var(--rzp-ink)]">Not settled</p>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
              This record never reached RECOVERED, so no settlement webhook was applied to it.
            </p>
          </div>
        );
      }
      return (
        <>
          <div className="mb-2.5 flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
            <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[var(--rzp-blue-600)]">
              {decision.paymentLinkId ? 'payment_link.paid' : 'settled'}
            </span>
            <ArrowRight size={10} strokeWidth={2.6} className="text-[var(--rzp-ink-faint)]" />
            <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-bold text-emerald-700">
              RECOVERED
            </span>
          </div>
          <Fact label="Payment Link ID" value={decision.paymentLinkId} missing="demo run — no live link" />
          <Fact label="Recovery payment ID" value={decision.recoveryPaymentId} missing="—" />
          <Fact label="Amount recovered" value={formatCurrencyFull(record.amount)} />
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">{settled.details}</p>
          <EntryRef entry={settled} />
        </>
      );
    }

    default:
      return null;
  }
}

/** Whether this stage actually happened for the selected record. */
function stageReached(stage, decision, record) {
  switch (stage.key) {
    case 'failed': return true;
    case 'diagnose':
    case 'classify': return Boolean(decision.diagnosis);
    case 'policy': return Boolean(decision.policyEvaluated);
    case 'action': return Boolean(decision.action);
    case 'settlement': return record.recovery_state === 'RECOVERED';
    default: return false;
  }
}

export default function DecisionPipeline({ record, decision }) {
  return (
    <ol className="space-y-3">
      {STAGES.map((stage, i) => {
        const reached = stageReached(stage, decision, record);
        const tone = reached ? TONE[stage.tone] : HOLLOW;
        const Icon = stage.icon;
        const isLast = i === STAGES.length - 1;

        return (
          <li key={stage.key} className="relative">
            {!isLast && (
              <span
                className={`absolute left-[19px] top-11 bottom-[-12px] w-0 border-l-2 ${
                  reached ? 'border-[var(--rzp-border-strong)]' : 'border-dashed border-[var(--rzp-border)]'
                }`}
              />
            )}

            <div className="flex gap-3">
              <span
                className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 ring-4 ring-white ${tone.dot}`}
              >
                <Icon size={17} strokeWidth={2.3} />
              </span>

              <div className="min-w-0 flex-1 rounded-2xl border border-[var(--rzp-border)] bg-white">
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--rzp-border)] px-4 py-2.5">
                  <span className="flex items-baseline gap-2">
                    <span className="font-mono text-[10px] font-bold text-[var(--rzp-ink-faint)]">
                      {String(stage.n).padStart(2, '0')}
                    </span>
                    <span className={`text-sm font-bold ${tone.text}`}>{stage.label}</span>
                    {!reached && (
                      <span className="rounded border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-1.5 py-px font-mono text-[9px] uppercase tracking-wider text-[var(--rzp-ink-faint)]">
                        not reached
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">{stage.source}</span>
                </div>

                <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
                  {/* How it works — documentation. */}
                  <div>
                    <span className="mb-1.5 block font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
                      How it works
                    </span>
                    {stage.how.map((p, j) => (
                      <p key={j} className="mb-1.5 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)] last:mb-0">
                        {p}
                      </p>
                    ))}
                  </div>

                  {/* What happened — evidence. */}
                  <div className="rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3">
                    <span className="mb-1.5 flex items-center gap-1.5 font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
                      <Link2 size={9} strokeWidth={2.4} />
                      What happened here
                    </span>
                    {reached || stage.key === 'action' || stage.key === 'settlement' ? (
                      <Evidence stage={stage} record={record} decision={decision} />
                    ) : (
                      <p className="text-[11px] italic text-[var(--rzp-ink-faint)]">
                        This record never reached this stage.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
