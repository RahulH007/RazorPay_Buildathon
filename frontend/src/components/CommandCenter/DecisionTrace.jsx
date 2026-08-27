/**
 * RecoverOS — Decision Trace
 *
 * One payment's path down five fixed stages: the event, the diagnosis, the
 * policy decision, the action, the outcome. Stages the record never reached
 * are drawn hollow with a dashed spine, so where a recovery stopped is a
 * shape rather than a sentence.
 *
 * The three annotations on the rail are the product's whole claim, attached
 * to the stage that proves each one: the model only ever recommends, the
 * policy engine alone decides, and the ledger is what makes both checkable.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import {
  AlertCircle,
  Ban,
  Bot,
  CircleCheck,
  GitBranch,
  Send,
  ShieldCheck,
  Zap,
} from 'lucide-react';

import { decisionStatus, reasonMeta } from '../../utils/decisions';
import { formatCurrencyFull } from '../../utils/formatters';

const CHANNEL_LABEL = {
  WHATSAPP_LINK_SENT: 'WhatsApp payment link',
  RETRY_SILENT_ATTEMPT: 'Silent retry',
  MANDATE_RESEQUENCED: 'UPI mandate re-sequence',
  VOICE_CALL_INITIATED: 'Hinglish voice call',
};

const TONE = {
  rose: { dot: 'border-rose-300 bg-rose-100 text-rose-700', text: 'text-rose-700' },
  blue: { dot: 'border-blue-300 bg-blue-100 text-[var(--rzp-blue-600)]', text: 'text-[var(--rzp-blue-600)]' },
  violet: { dot: 'border-violet-300 bg-violet-100 text-violet-700', text: 'text-violet-700' },
  emerald: { dot: 'border-emerald-300 bg-emerald-100 text-emerald-700', text: 'text-emerald-700' },
  amber: { dot: 'border-amber-300 bg-amber-100 text-amber-700', text: 'text-amber-700' },
  slate: { dot: 'border-slate-300 bg-slate-100 text-slate-600', text: 'text-slate-600' },
};

const HOLLOW = {
  dot: 'border-dashed border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-faint)]',
  text: 'text-[var(--rzp-ink-faint)]',
};

/** Build the five stages from the ledger-derived decision. */
function buildStages(record, decision) {
  const status = decisionStatus(decision, record);
  const meta = decision ? reasonMeta(decision.reasonCode) : null;

  // 1. EVENT — always reached; a record exists because a payment failed.
  const event = {
    stage: 'Event',
    icon: AlertCircle,
    tone: 'rose',
    reached: true,
    title: 'payment.failed',
    lines: [record.error_reason, formatCurrencyFull(record.amount)].filter(Boolean),
  };

  // 2. DIAGNOSIS — the rule engine or the model.
  const d = decision?.diagnosis;
  const isModel = d?.actor === 'llm_agent';
  const diagnosis = {
    stage: 'Diagnosis',
    icon: isModel ? Bot : GitBranch,
    tone: isModel ? 'violet' : 'blue',
    reached: Boolean(d),
    title: d ? d.failureClass || record.failure_class || 'classified' : 'Not diagnosed',
    lines: d
      ? [
          isModel ? 'AI diagnosis · llm_agent' : 'Deterministic rule · rule_engine',
          decision.confidence != null
            ? `${(decision.confidence * 100).toFixed(0)}% confidence`
            : isModel
            ? null
            : 'no model call, no cost',
        ].filter(Boolean)
      : ['the rules did not reach a class'],
    rail: 'AI recommends.',
  };

  // 3. POLICY — reached only when policy.py actually ran on the record.
  const policyRan = Boolean(decision?.policyEvaluated);
  const policy = {
    stage: 'Policy',
    icon: policyRan ? ShieldCheck : Ban,
    tone: policyRan ? status.tone : 'slate',
    reached: policyRan,
    title: policyRan ? status.code : 'Not evaluated',
    lines: policyRan
      ? [meta?.headline || meta?.label].filter(Boolean)
      : ['held before it reached the policy engine'],
    rail: 'Policy decides.',
  };

  // 4. ACTION — what was actually sent, and what it cost.
  const action = {
    stage: 'Action',
    icon: decision?.action ? Send : Ban,
    tone: decision?.action ? 'blue' : 'slate',
    reached: Boolean(decision?.action),
    title: decision?.action
      ? CHANNEL_LABEL[decision.action.channel] || decision.action.channel
      : 'No action taken',
    lines: decision?.action
      ? [
          `₹${decision.spendInr.toFixed(2)} spent`,
          `${decision.action.attempts} ${decision.action.attempts === 1 ? 'attempt' : 'attempts'}`,
        ]
      : ['₹0.00 additional spend', 'no customer was contacted'],
  };

  // 5. OUTCOME — where it ended, or where it is waiting.
  const state = record.recovery_state;
  const recovered = state === 'RECOVERED';
  const outcome = {
    stage: 'Outcome',
    icon: recovered ? CircleCheck : Zap,
    tone: status.tone,
    reached: true,
    title: recovered ? 'RECOVERED' : status.code === 'PROCEED' ? 'In progress' : status.code,
    lines: recovered
      ? [
          decision?.paymentLinkId ? 'payment_link.paid' : 'settled',
          decision?.recoveryPaymentId || null,
        ].filter(Boolean)
      : [meta?.label || state].filter(Boolean),
    rail: 'Ledger proves.',
  };

  return [event, diagnosis, policy, action, outcome];
}

export default function DecisionTrace({ record, decision }) {
  const stages = buildStages(record, decision);
  const stoppedAt = stages.findIndex((s) => !s.reached);

  return (
    <ol className="relative">
      {stages.map((s, i) => {
        const tone = s.reached ? TONE[s.tone] || TONE.slate : HOLLOW;
        const Icon = s.icon;
        const isLast = i === stages.length - 1;
        // The spine goes dashed from the first unreached stage onward, so the
        // break in the line is literally where the pipeline stopped.
        const spineBroken = stoppedAt >= 0 && i >= stoppedAt;

        return (
          <li key={s.stage} className="relative flex gap-3 pb-3 last:pb-0">
            {!isLast && (
              <span
                className={`absolute left-[15px] top-8 bottom-0 w-0 border-l-2 ${
                  spineBroken
                    ? 'border-dashed border-[var(--rzp-border-strong)]'
                    : 'border-solid border-[var(--rzp-border-strong)]'
                }`}
              />
            )}

            <span
              className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 ring-4 ring-white ${tone.dot}`}
            >
              <Icon size={14} strokeWidth={2.4} />
            </span>

            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
                  {s.stage}
                </span>
                {s.rail && (
                  <span className="font-mono text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--rzp-ink-faint)]/70">
                    · {s.rail}
                  </span>
                )}
                {i === stoppedAt && (
                  <span className="rounded border border-[var(--rzp-border-strong)] bg-[var(--rzp-surface-alt)] px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-muted)]">
                    stopped here
                  </span>
                )}
              </div>

              <div className={`mt-0.5 text-[13px] font-bold leading-tight ${tone.text}`}>
                {s.title}
              </div>

              {s.lines.length > 0 && (
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  {s.lines.map((line, j) => (
                    <span
                      key={j}
                      className="font-mono text-[10px] leading-tight text-[var(--rzp-ink-muted)]"
                    >
                      {j > 0 && <span className="mr-2 text-[var(--rzp-ink-faint)]">·</span>}
                      {line}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
