/**
 * RecoverOS — Trust strip
 *
 * What a reviewer should know about this system's footing before reading a
 * single number, and — importantly — how each claim is backed.
 *
 * Two treatments, deliberately not one. The hash chain is re-verified live
 * against /api/ledger/verify and gets a tick that means something. Signed
 * webhooks and exactly-once settlement are properties of the code, not
 * runtime state this API reports, so they are marked as guaranteed in source
 * and name the file a reviewer can read. Painting four identical green ticks
 * would have made the one real check worth no more than the three asserted
 * ones.
 *
 * The mode chip is a disclaimer, not a proof: nothing here moves live money,
 * and the strip says so first.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { AlertTriangle, Check, FileCode2, FlaskConical, Loader2 } from 'lucide-react';

// Claims that hold because the code makes them hold. Each names its source so
// the assertion is checkable by reading, even though it is not checkable by
// calling.
const CODE_GUARANTEES = [
  {
    key: 'webhooks',
    label: 'Signed webhooks',
    detail: 'HMAC-SHA256',
    source:
      'backend/app/routes/webhooks.py — verify_webhook_signature() compares the '
      + 'HMAC over the exact bytes received and fails closed outside demo mode.',
  },
  {
    key: 'settlement',
    label: 'Exactly-once settlement',
    detail: 'replay-safe',
    source:
      'backend/tests/test_duplicate_webhook_exactly_once.py — a repeated '
      + 'payment_link.paid settles the record once and never twice.',
  },
];

function Chip({ tone, icon: Icon, label, detail, title, spin }) {
  const tones = {
    amber: 'border-amber-300 bg-amber-50 text-amber-800',
    emerald: 'border-[#A6F4C5] bg-[#ECFDF3] text-[var(--rzp-green-dark)]',
    rose: 'border-rose-300 bg-rose-50 text-rose-700',
    muted: 'border-[var(--rzp-border)] bg-white text-[var(--rzp-ink-muted)]',
  };

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 ${tones[tone]}`}
    >
      <Icon
        size={12}
        strokeWidth={2.6}
        className={`shrink-0 ${spin ? 'animate-spin' : ''}`}
      />
      <span className="font-mono text-[10px] font-bold uppercase tracking-wider">{label}</span>
      {detail && (
        <span className="font-mono text-[10px] opacity-70">{detail}</span>
      )}
    </span>
  );
}

export default function TrustStrip({ chain, checking }) {
  return (
    <section className="flex flex-wrap items-center gap-2 rounded-2xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-3 py-2.5">
      {/* Scope disclaimer, first and unmissable. */}
      <Chip
        tone="amber"
        icon={FlaskConical}
        label="Real Razorpay Test Mode"
        title={
          'Test-mode credentials only. Payment Links, webhooks and settlement run '
          + 'against Razorpay test keys — no live money is moved or recovered.'
        }
      />

      <span className="hidden h-4 w-px bg-[var(--rzp-border-strong)] sm:block" />

      {/* The one claim re-checked on this page load. */}
      {checking ? (
        <Chip tone="muted" icon={Loader2} label="Verifying chain" spin />
      ) : chain?.valid ? (
        <Chip
          tone="emerald"
          icon={Check}
          label="Hash-chained audit"
          detail={`${(chain.entries_checked ?? 0).toLocaleString('en-IN')} entries verified`}
          title={
            `Checked live just now via GET /api/ledger/verify: every entry hash `
            + `recomputed and every prev_hash link walked. ${chain.reason}.`
          }
        />
      ) : chain ? (
        <Chip
          tone="rose"
          icon={AlertTriangle}
          label="Chain broken"
          detail={`at #${chain.first_broken_sequence}`}
          title={chain.reason}
        />
      ) : (
        <Chip tone="muted" icon={AlertTriangle} label="Chain unverified" detail="API unreachable" />
      )}

      {/* Properties of the source, marked as such. */}
      {CODE_GUARANTEES.map((g) => (
        <Chip
          key={g.key}
          tone="muted"
          icon={FileCode2}
          label={g.label}
          detail={g.detail}
          title={`Guaranteed in source, not measured here.\n${g.source}`}
        />
      ))}

      {/* The legend earns its space: it is what stops the two grey chips from
          being read as the same kind of claim as the green one. */}
      <span className="ml-auto hidden items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-[var(--rzp-ink-faint)] lg:inline-flex">
        <Check size={9} strokeWidth={3} className="text-[var(--rzp-green-dark)]" />
        checked live
        <span className="text-[var(--rzp-border-strong)]">·</span>
        <FileCode2 size={9} strokeWidth={2.4} />
        guaranteed in source
      </span>
    </section>
  );
}
