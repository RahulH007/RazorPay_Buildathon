/**
 * RecoverOS — Why this customer?
 *
 * The drawer already explains what went wrong and what policy decided. This
 * card answers the question a recovery agent asks before either: who is this
 * person, what has worked on them before, and is now the right moment.
 *
 * Two things it refuses to do, both visible in the markup:
 *
 *   It never fills a gap. A contact with no history renders the "not enough
 *   history" state and no channel claim at all — not a confident-looking card
 *   assembled from one data point. The backend decides that, via `sufficiency`,
 *   and this component only renders the verdict.
 *
 *   It never implies the recommendation was acted on. When the customer's
 *   history and the policy ladder disagree, the card says which one the
 *   executor will follow, and it is not the one on the left.
 *
 * Every value is served by /api/audit/{payment_id}, which the drawer already
 * fetches. Nothing is computed here.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { Clock, ShieldCheck, User } from 'lucide-react';

import { CHANNEL_ICONS } from '../../utils/formatters';

const CHANNEL_LABELS = {
  silent_retry: 'Silent retry',
  whatsapp_link: 'WhatsApp link',
  upi_resequence: 'UPI resequence',
  hinglish_voice: 'Hinglish voice',
  human_queue: 'Human escalation',
};

const SUFFICIENCY_TONE = {
  sufficient: 'border-[#A6F4C5] bg-[#ECFDF3] text-[var(--rzp-green-dark)]',
  thin: 'border-amber-300 bg-amber-50 text-amber-800',
  none: 'border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-muted)]',
};

const SUFFICIENCY_LABEL = {
  sufficient: 'history: sufficient',
  thin: 'history: thin',
  none: 'history: not enough',
};

function channelLabel(channel) {
  if (!channel) return 'No automated action';
  return CHANNEL_LABELS[channel] || channel;
}

function Section({ title, children }) {
  return (
    <div>
      <div className="font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
        {title}
      </div>
      <div className="mt-1 text-[11px] leading-snug text-[var(--rzp-ink)]">{children}</div>
    </div>
  );
}

export default function WhyThisCustomer({ insight }) {
  if (!insight) return null;

  const sufficiency = insight.sufficiency || 'none';
  const timing = insight.timing || {};
  const evidence = insight.evidence || [];
  const overridden = insight.overridden_by_policy;

  return (
    <section className="rounded-xl border border-[var(--rzp-border)] bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
          <User size={11} strokeWidth={2.4} />
          Why this customer?
        </h3>
        <span className="inline-flex items-center gap-2">
          <span
            className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${SUFFICIENCY_TONE[sufficiency]}`}
            title={insight.sufficiency_reason}
          >
            {SUFFICIENCY_LABEL[sufficiency]}
          </span>
          <span className="font-mono text-[10px] font-bold text-[var(--rzp-ink)]">
            {Math.round((insight.confidence ?? 0) * 100)}%
          </span>
        </span>
      </div>

      <div className="space-y-2.5">
        <Section title="Evidence">
          {/* A contact with no history gets one honest line, and the backend
              is what decides that — see sufficiency above. */}
          <ul className="space-y-0.5">
            {evidence.map((line) => (
              <li key={line} className="flex gap-1.5">
                <span className="text-[var(--rzp-border-strong)]">·</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Why this channel?">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono font-bold">
              <span aria-hidden="true">{CHANNEL_ICONS[insight.recommended_channel] || '•'}</span>{' '}
              {channelLabel(insight.recommended_channel)}
            </span>
            {overridden && (
              <span
                className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-amber-800"
                title={
                  'The customer’s history and the escalation ladder disagree here. '
                  + 'The ladder wins: policy decides what runs, and this recommendation '
                  + 'is recorded rather than executed.'
                }
              >
                policy will use {channelLabel(insight.policy_ladder_next)}
              </span>
            )}
          </span>
          <p className="mt-1 text-[var(--rzp-ink-muted)]">{insight.rationale}</p>
        </Section>

        <Section title="Why now?">
          <span className="inline-flex items-baseline gap-1.5">
            <Clock size={10} strokeWidth={2.4} className="translate-y-0.5 shrink-0" />
            <span className={timing.act_now ? 'font-bold' : 'font-bold text-amber-800'}>
              {timing.act_now ? 'Clear to act now' : 'Hold'}
            </span>
          </span>
          <p className="mt-0.5 text-[var(--rzp-ink-muted)]">{timing.why}</p>
        </Section>
      </div>

      <div
        className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5"
        title={
          'This reading is arithmetic over the customer’s own past records. It is '
          + 'recorded on the ledger and never executed: the policy engine and the '
          + 'safety guard evaluate the record independently and may refuse.'
        }
      >
        <ShieldCheck size={11} strokeWidth={2.6} className="shrink-0 text-[var(--rzp-blue-600)]" />
        <span className="font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-blue-600)]">
          {insight.notice || 'AI ADVISORY — POLICY/GUARDRAILS CONTROL EXECUTION'}
        </span>
      </div>
    </section>
  );
}
