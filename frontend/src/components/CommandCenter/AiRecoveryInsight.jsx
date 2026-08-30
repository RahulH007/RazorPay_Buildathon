/**
 * RecoverOS — AI Recovery Insight
 *
 * What the model made of the failures Razorpay's error vocabulary does not
 * cover — and, stated as plainly as the reading itself, that it decided none
 * of them.
 *
 * The banner is not decoration. This panel is the one place on the dashboard
 * where a model's words are shown to a reviewer, and the single most damaging
 * misreading available to them is "the AI chose to send this person a payment
 * link". It did not. It named a failure class; the channel beside it is what
 * policy.py's escalation ladder opens with for that class, looked up in code.
 * So the banner sits above the cards rather than below, and every card repeats
 * that the recommendation was recorded, not executed.
 *
 * Every field is served by /api/metrics/dashboard over the same cohort as the
 * tiles above. Nothing is computed here, and a record with no AI reading
 * renders nothing rather than an empty-looking card.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { Brain, ShieldCheck, TriangleAlert } from 'lucide-react';

import { CHANNEL_ICONS, truncateId } from '../../utils/formatters';

const CHANNEL_LABELS = {
  silent_retry: 'Silent retry',
  whatsapp_link: 'WhatsApp link',
  upi_resequence: 'UPI resequence',
  hinglish_voice: 'Hinglish voice',
  human_queue: 'Human escalation',
};

function channelLabel(channel) {
  if (!channel) return 'No automated action';
  return CHANNEL_LABELS[channel] || channel;
}

/**
 * Confidence, coloured by whether this system would act on it. The threshold
 * is a backend decision and arrives already applied as `review_required`, so
 * the UI never re-derives it and the two can never disagree on screen.
 */
function Confidence({ value, reviewRequired }) {
  const pct = Math.round((value ?? 0) * 100);
  const tone = reviewRequired
    ? 'border-amber-300 bg-amber-50 text-amber-800'
    : 'border-[#A6F4C5] bg-[#ECFDF3] text-[var(--rzp-green-dark)]';

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-lg border px-2 py-0.5 font-mono text-[10px] font-bold ${tone}`}
      title={
        reviewRequired
          ? 'Below the confidence threshold this system acts on. Recorded for human review.'
          : 'Above the confidence threshold — the policy engine still decides independently.'
      }
    >
      {reviewRequired && <TriangleAlert size={10} strokeWidth={2.6} />}
      {pct}%
    </span>
  );
}

function InsightCard({ rec }) {
  return (
    <article className="rounded-xl border border-[var(--rzp-border)] bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
          {truncateId(rec.payment_id)}
          <span className="ml-1.5 text-[var(--rzp-border-strong)]">·</span>
          <span className="ml-1.5 normal-case tracking-normal text-[var(--rzp-ink-muted)]">
            {rec.evidence?.error_reason || 'unknown reason'}
          </span>
        </span>
        <Confidence value={rec.confidence} reviewRequired={rec.review_required} />
      </div>

      <dl className="mt-2 space-y-2">
        <div>
          <dt className="font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
            Failure interpretation
          </dt>
          <dd className="mt-0.5 text-[11px] leading-snug text-[var(--rzp-ink)]">
            {rec.interpretation || '—'}
          </dd>
        </div>

        <div>
          <dt className="font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
            Recommended action
          </dt>
          <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[11px] text-[var(--rzp-ink)]">
            <span className="font-mono font-bold">
              <span aria-hidden="true">{CHANNEL_ICONS[rec.recommended_channel] || '•'}</span>{' '}
              {channelLabel(rec.recommended_channel)}
            </span>
            <span className="text-[10px] text-[var(--rzp-ink-muted)]">
              {rec.model_suggested_action}
            </span>
          </dd>
        </div>

        <div>
          <dt className="font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
            Why
          </dt>
          <dd className="mt-0.5 text-[11px] leading-snug text-[var(--rzp-ink-muted)]">
            {rec.rationale || '—'}
          </dd>
        </div>
      </dl>
    </article>
  );
}

export default function AiRecoveryInsight({ metrics }) {
  const insight = metrics?.ai_insight;
  const recommendations = insight?.recommendations || [];

  // No slow-path failure in this cohort means the model was never consulted,
  // which is the ordinary case and not something to apologise for with an
  // empty panel.
  if (!recommendations.length) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="inline-flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
          <Brain size={12} strokeWidth={2.4} />
          AI Recovery Insight
        </h2>
        <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
          {insight.count} reading{insight.count === 1 ? '' : 's'} on this cohort
          {insight.review_required > 0 && ` · ${insight.review_required} flagged for review`}
        </span>
      </div>

      {/* The disclaimer leads. A reviewer who reads one line of this panel
          should read this one. */}
      <div
        className="mb-3 flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2"
        title={
          'The model names a failure class. The channel shown is what the deterministic '
          + 'escalation ladder in app/policy.py opens with for that class — the model '
          + 'never names one. Execution is authorised by the policy engine and the '
          + 'safety guard, which evaluate the record independently and may refuse.'
        }
      >
        <ShieldCheck
          size={13}
          strokeWidth={2.6}
          className="shrink-0 text-[var(--rzp-blue-600)]"
        />
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--rzp-blue-600)]">
          {insight.notice || 'AI ADVISORY — POLICY/GUARDRAILS CONTROL EXECUTION'}
        </span>
      </div>

      <div className="grid gap-2 lg:grid-cols-2 2xl:grid-cols-3">
        {recommendations.map((rec) => (
          <InsightCard key={rec.payment_id} rec={rec} />
        ))}
      </div>

      <p className="mt-2 font-mono text-[9px] uppercase tracking-wider text-[var(--rzp-ink-faint)]">
        every reading above is one zero-cost entry on the hash chain · recorded, not executed
      </p>
    </section>
  );
}
