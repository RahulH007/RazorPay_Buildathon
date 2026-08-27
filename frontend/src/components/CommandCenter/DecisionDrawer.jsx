/**
 * RecoverOS — Decision drawer
 *
 * An operational decision panel, not a conversation. It answers five
 * questions in fixed order — what was decided, what the diagnosis found,
 * which gates ran, what was done, how it ended — and then shows the ledger
 * entries that prove all five.
 *
 * Language is deliberately short and declarative: "Policy blocked recovery:
 * consent withdrawn", never a paragraph explaining that the system determined
 * something. A reviewer should be able to read the verdict and the trace in
 * well under ten seconds and drill down only if they doubt it.
 *
 * The drawer never states anything the ledger did not. Identifiers a demo run
 * does not produce render as absent rather than as a plausible placeholder,
 * because a fabricated id in a panel about provenance discredits the panel.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useEffect } from 'react';
import {
  Ban,
  Bot,
  Check,
  CircleCheck,
  Copy,
  Fingerprint,
  GitBranch,
  Loader2,
  Loader,
  Minus,
  PauseCircle,
  Route,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Wallet,
  X,
} from 'lucide-react';

import AuditTimeline from './AuditTimeline';
import DecisionTrace from './DecisionTrace';
import PolicyChecks from './PolicyChecks';
import { FAILURE_CLASS_LABELS, formatCurrencyFull } from '../../utils/formatters';
import {
  buildPolicyChecks,
  decisionStatus,
  linkStatus,
  outcomeBucket,
  reasonMeta,
} from '../../utils/decisions';

const CHANNEL_LABEL = {
  WHATSAPP_LINK_SENT: 'WhatsApp payment link',
  RETRY_SILENT_ATTEMPT: 'Silent retry',
  MANDATE_RESEQUENCED: 'UPI mandate re-sequence',
  VOICE_CALL_INITIATED: 'Hinglish voice call',
};

const PILL = {
  rose: 'border-rose-200 bg-rose-50 text-rose-700',
  blue: 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)]',
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  amber: 'border-amber-200 bg-amber-50 text-amber-700',
  violet: 'border-violet-200 bg-violet-50 text-violet-700',
  slate: 'border-slate-200 bg-slate-50 text-slate-600',
};

// The decision banner. One tone per status, carried through to the trace.
const STATUS_STYLE = {
  RECOVERED: { icon: CircleCheck, panel: 'border-emerald-300 bg-emerald-50', chip: 'bg-emerald-600', text: 'text-emerald-900' },
  PROCEED: { icon: ShieldCheck, panel: 'border-blue-300 bg-blue-50', chip: 'bg-[var(--rzp-blue-600)]', text: 'text-[#0C2451]' },
  DEFER: { icon: PauseCircle, panel: 'border-violet-300 bg-violet-50', chip: 'bg-violet-600', text: 'text-violet-900' },
  HOLD: { icon: Loader, panel: 'border-slate-300 bg-slate-50', chip: 'bg-slate-600', text: 'text-slate-900' },
  STOP: { icon: Ban, panel: 'border-rose-300 bg-rose-50', chip: 'bg-rose-600', text: 'text-rose-900' },
};

function Section({ icon: Icon, title, aside, children }) {
  return (
    <section className="border-t border-[var(--rzp-border)] px-5 py-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--rzp-ink)]">
          {Icon && <Icon size={13} strokeWidth={2.2} className="text-[var(--rzp-ink-faint)]" />}
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Field({ label, value, mono = true, missing = 'not issued' }) {
  const copy = () => {
    if (value && navigator.clipboard) navigator.clipboard.writeText(value).catch(() => {});
  };

  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed border-[var(--rzp-border)] py-1.5 last:border-b-0">
      <span className="shrink-0 text-[11px] text-[var(--rzp-ink-muted)]">{label}</span>
      {value ? (
        <button
          onClick={copy}
          title="Copy"
          className={`group inline-flex min-w-0 cursor-pointer items-center gap-1.5 text-[11px] font-semibold text-[var(--rzp-ink)] ${
            mono ? 'font-mono' : ''
          }`}
        >
          <span className="truncate">{value}</span>
          <Copy
            size={10}
            strokeWidth={2.2}
            className="shrink-0 text-[var(--rzp-ink-faint)] opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
      ) : (
        <span className="font-mono text-[11px] italic text-[var(--rzp-ink-faint)]">{missing}</span>
      )}
    </div>
  );
}

export default function DecisionDrawer({
  record,
  decision,
  loading,
  error,
  onClose,
  onOpenSimulator,
}) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!record) return null;

  const state = record.recovery_state || 'INGESTED';
  const status = decisionStatus(decision, record);
  const meta = decision ? reasonMeta(decision.reasonCode) : null;
  const style = STATUS_STYLE[status.code];
  const StatusIcon = style.icon;
  const verification = decision?.verification;
  const link = linkStatus(decision);

  const bucket = outcomeBucket(record, decision);
  const gates = decision ? buildPolicyChecks(decision) : [];
  const ran = gates.filter((g) => g.status !== 'skipped').length;
  const isModel = decision?.diagnosis?.actor === 'llm_agent';

  const seqFrom = decision?.run?.[0]?.sequence_no;
  const seqTo = decision?.run?.[decision.run.length - 1]?.sequence_no;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-[#162F56]/30 backdrop-blur-sm animate-overlay-in"
        onClick={onClose}
      />

      <aside className="relative flex h-full w-full max-w-[620px] flex-col border-l border-[var(--rzp-border)] bg-white shadow-[-16px_0_48px_rgba(22,47,86,0.14)] animate-drawer-in">
        {/* Identity */}
        <header className="shrink-0 border-b border-[var(--rzp-border)] px-5 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-xl font-extrabold tracking-tight text-[var(--rzp-ink)]">
                  {formatCurrencyFull(record.amount)}
                </span>
                <span className="text-xs font-semibold text-[var(--rzp-ink)]">
                  {record.customer_name}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-baseline gap-2 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                <span>{record.payment_id}</span>
                <span>·</span>
                <span>{record.method}</span>
                <span>·</span>
                <span>{FAILURE_CLASS_LABELS[record.failure_class] || 'unclassified'}</span>
              </div>
            </div>

            <button
              onClick={onClose}
              aria-label="Close decision drawer"
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-[var(--rzp-border)] text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)] hover:text-[var(--rzp-ink)]"
            >
              <X size={16} strokeWidth={2} />
            </button>
          </div>
        </header>

        <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
          {loading && !decision ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center font-mono text-xs text-[var(--rzp-ink-muted)]">
              <Loader2 size={16} strokeWidth={2.4} className="animate-spin" />
              Reading the ledger…
            </div>
          ) : error ? (
            <div className="px-5 py-16 text-center">
              <p className="text-xs font-bold text-[var(--rzp-ink)]">
                Could not read the ledger for this payment.
              </p>
              <p className="mt-1.5 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
                GET /api/audit/{record.payment_id} failed — this says nothing about
                whether entries exist. Check the API and reopen.
              </p>
            </div>
          ) : !decision ? (
            <div className="py-16 text-center font-mono text-xs text-[var(--rzp-ink-faint)]">
              No ledger entries recorded for this payment yet.
            </div>
          ) : (
            <>
              {/* 1 · DECISION ------------------------------------------- */}
              <div className="px-5 py-4">
                <div className={`rounded-xl border-2 p-4 ${style.panel}`}>
                  <div className="flex items-center gap-3">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white ${style.chip}`}
                    >
                      <StatusIcon size={20} strokeWidth={2.4} />
                    </span>
                    <div className="min-w-0">
                      <div className={`text-xl font-extrabold uppercase leading-none tracking-tight ${style.text}`}>
                        {status.code}
                      </div>
                      <p className={`mt-1 text-[13px] font-bold leading-tight ${style.text}`}>
                        {meta?.headline || meta?.label}
                      </p>
                    </div>
                  </div>

                  {decision.reasonText && (
                    <p className="mt-3 border-t border-current/15 pt-2.5 text-xs leading-relaxed text-[var(--rzp-ink)]">
                      {decision.reasonText}
                    </p>
                  )}
                </div>
              </div>

              {/* THE TRACE ---------------------------------------------- */}
              <Section
                icon={Route}
                title="Decision trace"
                aside={
                  <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                    AI recommends · Policy decides · Ledger proves
                  </span>
                }
              >
                <DecisionTrace record={record} decision={decision} />
              </Section>

              {/* 2 · WHAT AI FOUND -------------------------------------- */}
              <Section
                icon={isModel ? Bot : GitBranch}
                title="What the diagnosis found"
                aside={
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${
                      isModel ? PILL.violet : PILL.blue
                    }`}
                    title={
                      isModel
                        ? 'The rule map did not recognise this code, so the model was asked'
                        : 'Matched deterministically by the rule engine — no model call, no cost'
                    }
                  >
                    {isModel ? <Bot size={9} strokeWidth={2.4} /> : <GitBranch size={9} strokeWidth={2.4} />}
                    {isModel ? 'AI diagnosis' : 'Deterministic rule'}
                  </span>
                }
              >
                <div className="rounded-xl border border-[var(--rzp-border)] bg-white px-3 py-1.5">
                  <Field label="Failure reason" value={record.error_reason} />
                  <Field
                    label="Failure class"
                    value={decision.diagnosis?.failureClass || record.failure_class}
                    missing="not classified"
                  />
                  <Field label="Decided by" value={decision.diagnosis?.actor} missing="—" />
                  <Field
                    label="Confidence"
                    value={
                      decision.confidence != null
                        ? `${(decision.confidence * 100).toFixed(0)}%  (threshold 70%)`
                        : null
                    }
                    missing={isModel ? 'not scored' : 'n/a — rule match is exact'}
                  />
                </div>

                {decision.diagnosis?.text && (
                  <p className="mt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
                    {decision.diagnosis.text}
                  </p>
                )}

                {record.error_description && (
                  <p className="mt-2 font-mono text-[10px] leading-relaxed text-[var(--rzp-ink-faint)]">
                    gateway said: {record.error_description}
                  </p>
                )}

                {decision.rejections > 0 && (
                  <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700">
                    Output guard rejected {decision.rejections} generated{' '}
                    {decision.rejections === 1 ? 'message' : 'messages'}. A fixed template was sent
                    instead.
                  </p>
                )}
              </Section>

              {/* 3 · POLICY DECISION ------------------------------------ */}
              <Section
                icon={ShieldCheck}
                title="Policy decision"
                aside={
                  <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                    {ran} of {gates.length} gates evaluated
                  </span>
                }
              >
                <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-[var(--rzp-ink-muted)]">
                  <span className="inline-flex items-center gap-1">
                    <Check size={10} strokeWidth={3} className="text-emerald-600" /> passed
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <X size={10} strokeWidth={3} className="text-amber-700" /> blocked
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Minus size={10} strokeWidth={3} className="text-slate-400" /> not evaluated
                  </span>
                  <span className="ml-auto text-[var(--rzp-ink-faint)]">cheapest first</span>
                </div>

                <PolicyChecks decision={decision} />
              </Section>

              {/* 4 · ACTION --------------------------------------------- */}
              <Section
                icon={Wallet}
                title="Action"
                aside={
                  <span className="font-mono text-[11px] font-bold text-[var(--rzp-ink)]">
                    ₹{decision.spendInr.toFixed(2)}
                  </span>
                }
              >
                {decision.action ? (
                  <>
                    <div className="rounded-xl border border-[var(--rzp-border)] bg-white px-3 py-1.5">
                      <Field
                        label="Channel"
                        value={CHANNEL_LABEL[decision.action.channel] || decision.action.channel}
                        mono={false}
                      />
                      <Field label="Cost" value={`₹${decision.spendInr.toFixed(2)}`} />
                      <Field label="Payment Link ID" value={decision.paymentLinkId} />
                      <Field
                        label="Link status"
                        value={link?.label}
                        mono={false}
                        missing="no link issued"
                      />
                    </div>

                    {link?.note && (
                      <p className="mt-1.5 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                        {link.note}
                      </p>
                    )}

                    <button
                      onClick={() => onOpenSimulator?.(record)}
                      className="mt-2.5 inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--rzp-blue-600)] bg-white px-2.5 py-1.5 text-[11px] font-bold text-[var(--rzp-blue-600)] transition-colors hover:bg-[var(--rzp-blue-050)]"
                    >
                      <Smartphone size={12} strokeWidth={2.2} />
                      Open on the phone simulator
                    </button>
                  </>
                ) : (
                  <div className="rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3">
                    <p className="text-[13px] font-bold text-[var(--rzp-ink)]">No action taken</p>
                    <p className="mt-1 font-mono text-[11px] text-[var(--rzp-ink-muted)]">
                      ₹0.00 additional spend · no customer contact
                    </p>
                    <p className="mt-2 border-t border-dashed border-[var(--rzp-border)] pt-2 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
                      {decision.reasonText || meta?.blurb}
                    </p>
                  </div>
                )}
              </Section>

              {/* 5 · OUTCOME -------------------------------------------- */}
              <Section
                icon={state === 'RECOVERED' ? CircleCheck : Ban}
                title="Outcome"
                aside={
                  /* The bucket label, not the raw recovery_state. A card in
                     the queue says "Held & deferred" and the bar above it
                     says the same; showing "FAILED_STOPPED" here made three
                     names for one thing. */
                  <span
                    className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${
                      PILL[status.tone]
                    }`}
                  >
                    {bucket.label}
                  </span>
                }
              >
                {state === 'RECOVERED' ? (
                  <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 text-[11px] leading-relaxed text-emerald-900">
                    {decision.outcomeEntry?.details
                      || 'Settled. The record reached RECOVERED.'}
                  </p>
                ) : (
                  <div className="rounded-lg border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-2.5">
                    <p className="text-[11px] font-bold text-[var(--rzp-ink)]">
                      Pipeline stopped at{' '}
                      {!decision.diagnosis
                        ? 'diagnosis'
                        : !decision.policyEvaluated
                        ? 'policy — never evaluated'
                        : !decision.action
                        ? 'action — nothing was sent'
                        : 'outcome — contacted, not settled'}
                      .
                    </p>
                    <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">
                      {decision.outcomeEntry?.details || decision.reasonText || meta?.blurb}
                    </p>
                  </div>
                )}
              </Section>

              {/* 6 · AUDIT PROOF ---------------------------------------- */}
              <Section
                icon={Fingerprint}
                title="Audit proof"
                aside={
                  verification && (
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${
                        verification.valid ? PILL.emerald : PILL.rose
                      }`}
                    >
                      {verification.valid ? (
                        <Check size={9} strokeWidth={3} />
                      ) : (
                        <ShieldAlert size={9} strokeWidth={2.4} />
                      )}
                      {verification.valid ? 'Chain verified' : 'Chain broken'}
                    </span>
                  )
                }
              >
                <div className="rounded-xl border border-[var(--rzp-border)] bg-white px-3 py-1.5">
                  <Field label="Original payment ID" value={record.payment_id} />
                  <Field label="Recovery payment ID" value={decision.recoveryPaymentId} />
                  <Field label="Payment Link ID" value={decision.paymentLinkId} />
                  <Field
                    label="Ledger sequence"
                    value={seqFrom != null ? `#${seqFrom} – #${seqTo}` : null}
                  />
                  <Field
                    label="Decision entry"
                    value={
                      decision.reasonEntry
                        ? `#${decision.reasonEntry.sequence_no} · ${decision.reasonEntry.entry_hash?.slice(0, 16)}…`
                        : null
                    }
                    missing="—"
                  />
                  <Field
                    label="Entries verified"
                    value={
                      verification ? `${verification.entries_checked} for this payment` : null
                    }
                    missing="—"
                  />
                </div>

                {verification && (
                  <p className="mt-1.5 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                    {verification.reason}
                  </p>
                )}

                <div className="mt-4">
                  <div className="mb-2.5 flex items-baseline justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--rzp-ink-muted)]">
                      Ledger entries
                    </span>
                    <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                      {decision.run.length} this run · {decision.totalEntries} total
                    </span>
                  </div>
                  <AuditTimeline decision={decision} />
                </div>
              </Section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
