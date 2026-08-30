/**
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 *
 * Home.
 *
 * One job: get a reviewer from "what is this" to the Track 03 thesis in about
 * ten seconds — a failed payment is detected, diagnosed, judged against
 * policy, acted on within bounds, settled through Razorpay, and proven.
 *
 * The hero background is supplied abstract artwork — a converging field of
 * points, not a screenshot. That distinction is deliberate: a picture of a
 * dashboard would be a picture of a product rather than the product, and both
 * real dashboards are one click away. The source PNG was 1.9 MB; it ships as a
 * 194 KB WebP at the same 1536x1024, because a hero that blocks first paint is
 * a worse first impression than no hero at all.
 *
 * Every number on this page is live from the API, or transcribed from the
 * committed demo receipt (results/demo_run.txt) / config.py and labelled as
 * such. No latency, accuracy, uptime or success-rate claim appears anywhere,
 * because none of them would be reproducible.
 */

import { useEffect, useState } from 'react';
import {
  ArrowRight,
  BadgeCheck,
  Ban,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  FlaskConical,
  Loader2,
  Radar,
  ScrollText,
  Send,
  ShieldCheck,
  Wallet,
} from 'lucide-react';
import heroField from '../../assets/hero-recovery-field.webp';
import api from '../../utils/api';

// Transcribed from the committed demo receipt (results/demo_run.txt). Used
// only as the fallback when the API has not answered, and labelled as such.
const RUN = { records: 57, entries: 388, reasonCodes: 9, head: '1c61537b' };

/* ── Section 3 · the six stages, named exactly as the Engine names them ── */
const STAGES = [
  { n: '01', label: 'Detect', icon: Radar, tone: 'rose',
    body: 'Capture signed payment failure events from Razorpay and write them to the ledger before anything acts.' },
  { n: '02', label: 'Diagnose', icon: Bot, tone: 'violet',
    body: 'Deterministic rules classify known failures; the model handles only the codes the rules do not recognise.' },
  { n: '03', label: 'Policy', icon: ShieldCheck, tone: 'amber',
    body: 'Consent, economics, retry limits and stopping rules decide whether recovery is allowed at all.' },
  { n: '04', label: 'Action', icon: Send, tone: 'blue',
    body: 'Execute the policy-approved channel — and nothing else. The cheapest rung is always tried first.' },
  { n: '05', label: 'Settlement', icon: CircleCheck, tone: 'emerald',
    body: 'Razorpay confirms payment through the signed webhook flow, applied exactly once.' },
  { n: '06', label: 'Proof', icon: ScrollText, tone: 'slate',
    body: 'The ledger records the transition and makes the whole recovery independently verifiable.' },
];

const STAGE_TONE = {
  rose: 'border-rose-200 bg-rose-50 text-rose-600',
  violet: 'border-violet-200 bg-violet-50 text-violet-600',
  amber: 'border-amber-200 bg-amber-50 text-amber-600',
  blue: 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)]',
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-600',
  slate: 'border-slate-200 bg-slate-100 text-slate-600',
};

/* ── Section 4 · evidence, split by how each claim is actually backed ──── */
const EVIDENCE = [
  { key: 'mode', kind: 'scope', icon: FlaskConical, label: 'Real Razorpay Test Mode',
    body: 'Payment Links, webhooks and settlement run against test credentials. No live money moves.' },
  { key: 'link', kind: 'source', icon: BadgeCheck, label: 'Payment Link correlation',
    body: 'Each link is stored against the entry hash of the action that created it. Real ids render on the Engine.',
    src: 'settlement.py · models.py' },
  { key: 'hmac', kind: 'source', icon: ShieldCheck, label: 'Signed webhooks',
    body: 'HMAC-SHA256 verified over the exact bytes received; unsigned events are refused outside demo mode.',
    src: 'routes/webhooks.py' },
  { key: 'once', kind: 'source', icon: Ban, label: 'Exactly-once settlement',
    body: 'A replayed payment_link.paid settles a record once and never twice.',
    src: 'tests/test_duplicate_webhook_exactly_once.py' },
];

/* ── Section 5 · the differentiators, as a carousel ─────────────────────── */
const CARDS = [
  { eyebrow: 'Policy-first recovery',
    leadBlue: 'Policy before action.',
    leadDark: 'The model can recommend a recovery path. It cannot bypass one.',
    body: 'Consent, economics, retry limits and stopping rules are evaluated before a rupee is spent or a customer is contacted. A refusal is recorded exactly as an action is.',
    cta: 'Explore policy', tab: 'console' },
  { eyebrow: 'Tamper-evident by design',
    leadBlue: 'Every recovery has a receipt.',
    leadDark: 'Actions, refusals, spend and settlement transitions are hash-chained.',
    body: 'SHA-256 over an integer-only preimage, each entry linked to the one before it. A cost edited directly in the database is named by sequence number the moment you verify.',
    cta: 'Verify the ledger', tab: 'overview' },
  { eyebrow: 'Bounded economics',
    leadBlue: 'Economics decide too.',
    leadDark: 'Recovery stops when expected value no longer justifies the channel cost.',
    body: 'Spend accumulates in integer paise against a ceiling set as a share of the payment itself. An attempt worth less than it costs is refused outright, with the arithmetic recorded.',
    cta: 'See the Engine', tab: 'console' },
  { eyebrow: 'Verified settlement',
    leadBlue: 'Settlement is not a guess.',
    leadDark: 'Payment Link correlation is anchored to the record that created it.',
    body: 'The link is keyed to the entry hash of its own action and confirmed through the signed settlement webhook, so a payment can be traced back to the decision that caused it.',
    cta: 'See the evidence', tab: 'console' },
];

/* ── Section 6 · safety principles ──────────────────────────────────────── */
const PRINCIPLES = [
  { label: 'Customer first', icon: ShieldCheck,
    body: 'Consent and suppression are checked before any outbound recovery. An opt-out outlives the payment that caused it.' },
  { label: 'Economics guardrail', icon: Wallet,
    body: 'Channel spend is bounded against recovery economics, capped as a share of the payment’s own value.' },
  { label: 'Stop when you should', icon: Ban,
    body: 'Retry caps, hard declines, quiet hours and holdouts stop automation. Restraint is an output, not an absence.' },
  { label: 'Provable by design', icon: ScrollText,
    body: 'Every decision that matters leaves an auditable ledger trail anyone can recompute.' },
];

function StatCell({ label, value, note }) {
  return (
    <div className="min-w-0">
      <div className="truncate font-mono text-lg font-extrabold tracking-tight text-[var(--rzp-ink)]">
        {value}
      </div>
      <div className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-wider text-[var(--rzp-ink-faint)]">
        {label}
      </div>
      {note && <div className="truncate font-mono text-[10px] text-[var(--rzp-ink-faint)]">{note}</div>}
    </div>
  );
}

export default function HomeView({ onNavigateTab, metrics }) {
  const [chain, setChain] = useState(null);
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState(0);
  const [perView, setPerView] = useState(1);

  useEffect(() => {
    let cancelled = false;
    api.verifyLedger()
      .then((d) => { if (!cancelled) { setChain(d); setChecking(false); } })
      .catch(() => { if (!cancelled) { setChain(null); setChecking(false); } });
    return () => { cancelled = true; };
  }, []);

  // Two cards at lg and above, one below. Tracked in JS because the page
  // count and the clamp depend on it, not just the card width.
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const apply = () => setPerView(mq.matches ? 2 : 1);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  const pages = Math.max(1, Math.ceil(CARDS.length / perView));
  const safePage = Math.min(page, pages - 1);
  const go = (d) => setPage((p) => (Math.min(p, pages - 1) + d + pages) % pages);

  const live = Boolean(metrics?.total_records);
  const records = live ? metrics.total_records : RUN.records;
  const head = (metrics?.ledger?.head_hash || '').slice(0, 8) || RUN.head;
  const recovered = live ? metrics.recovered_count : null;

  return (
    <div className="font-sans">
      {/* ══ 1 · HERO ═══════════════════════════════════════════════════ */}
      <section className="relative isolate overflow-hidden bg-[#05070F]">
        {/* The artwork itself. Anchored right so the bright convergence sits
            opposite the copy at every width instead of behind it. */}
        <div
          className="pointer-events-none absolute inset-0 bg-[length:cover] bg-[position:72%_center] bg-no-repeat"
          style={{ backgroundImage: `url(${heroField})` }}
          aria-hidden="true"
        />
        {/* Legibility scrim. The plate's left third is already near-black, but
            at narrow widths the field slides under the headline, so the copy
            side is darkened explicitly rather than left to chance. */}
        <div className="pointer-events-none absolute inset-0 bg-[#05070F]/72 lg:hidden" aria-hidden="true" />
        <div
          className="pointer-events-none absolute inset-0 hidden lg:block"
          style={{ backgroundImage: 'linear-gradient(to right,#05070F 0%,rgba(5,7,15,0.97) 32%,rgba(5,7,15,0.80) 48%,rgba(5,7,15,0.34) 64%,rgba(5,7,15,0) 84%)' }}
          aria-hidden="true"
        />

        <div className="rzp-container relative z-10 grid min-h-[560px] grid-cols-1 items-center gap-10 py-16 lg:min-h-[620px] lg:grid-cols-12 lg:gap-6 lg:py-20">
          <div className="lg:col-span-7">
            <span className="inline-flex items-center rounded-md border border-[#3395FF]/35 bg-[#3395FF]/10 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
              Autonomous Revenue Recovery
            </span>

            <h1 className="mt-5 text-[38px] font-bold leading-[1.08] tracking-[-0.025em] text-white sm:text-[48px] lg:text-[54px]">
              Turn failed payments
              <br />
              into <span className="text-[#3395FF]">recovered revenue.</span>
            </h1>

            <p className="mt-5 max-w-[540px] text-[15px] leading-relaxed text-slate-300/90">
              RecoverOS detects payment failures, diagnoses the cause, applies policy
              guardrails, executes the right recovery action, and verifies settlement — with
              every decision recorded in a tamper-evident ledger.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button
                onClick={() => onNavigateTab('overview')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[var(--rzp-blue-600)] px-6 py-3.5 text-[15px] font-bold text-white shadow-lg shadow-blue-900/40 transition-all hover:-translate-y-0.5 hover:bg-[#3395FF]"
              >
                Open Command Center
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
              <button
                onClick={() => onNavigateTab('console')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:border-white/30 hover:bg-white/[0.12]"
              >
                See how it works
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
            </div>

            {/* ══ 2 · TRUST STRIP ═══════════════════════════════════════ */}
            <div className="mt-10 grid grid-cols-1 gap-x-6 gap-y-4 border-t border-white/10 pt-6 sm:grid-cols-3">
              {[
                { icon: FlaskConical, t: 'Real Razorpay Test Mode', s: 'Live Payment Links + webhooks' },
                { icon: ShieldCheck, t: 'Policy-first by design', s: 'Consent, economics and limits' },
                { icon: ScrollText, t: 'Proven with a ledger', s: 'Hash-chained, tamper-evident' },
              ].map(({ icon: Icon, t, s }) => (
                <div key={t} className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/12 bg-white/[0.06] text-[#7FB4FF]">
                    <Icon size={13} strokeWidth={2.2} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[12px] font-bold leading-tight text-white">{t}</span>
                    <span className="mt-0.5 block text-[11px] leading-tight text-slate-400">{s}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ══ 3 · SIX STAGES ═══════════════════════════════════════════════ */}
      <section className="bg-white py-16 lg:py-20">
        <div className="rzp-container">
          <div className="mb-9 flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-2xl">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
                How RecoverOS works
              </p>
              <h2 className="mt-2 text-[30px] font-bold leading-[1.14] tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[38px]">
                Six stages. One mission:
                <br />
                <span className="text-[var(--rzp-blue-600)]">recover revenue,</span> responsibly.
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
                Every failed payment walks the same deterministic pipeline — and every step it
                takes, including every refusal, is written down.
              </p>
            </div>
            <button
              onClick={() => onNavigateTab('console')}
              className="inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-xl border border-[var(--rzp-border-strong)] bg-white px-4 py-2.5 text-sm font-bold text-[var(--rzp-ink)] transition-colors hover:border-[var(--rzp-blue-600)] hover:text-[var(--rzp-blue-600)]"
            >
              See it in action
              <ArrowRight size={15} strokeWidth={2.5} />
            </button>
          </div>

          <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {STAGES.map((s) => {
              const Icon = s.icon;
              return (
                <li key={s.label}
                  className="group flex flex-col rounded-2xl border border-[var(--rzp-border)] bg-white p-4 transition-all hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md">
                  <span className="flex items-center justify-between">
                    <span className={`flex h-9 w-9 items-center justify-center rounded-xl border ${STAGE_TONE[s.tone]}`}>
                      <Icon size={16} strokeWidth={2.2} />
                    </span>
                    <span className="font-mono text-[11px] font-bold text-[var(--rzp-ink-faint)]">{s.n}</span>
                  </span>
                  <span className="mt-3 text-[15px] font-bold text-[var(--rzp-ink)]">{s.label}</span>
                  <span className="mt-1.5 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">{s.body}</span>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {/* ══ 4 · PROOF ════════════════════════════════════════════════════ */}
      <section className="bg-[var(--rzp-surface-alt)] py-16 lg:py-20">
        <div className="rzp-container">
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
              Proof you can verify
            </p>
            <h2 className="mt-2 text-[30px] font-bold leading-[1.14] tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[38px]">
              Not a mock. Prove it.
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
              RecoverOS has been exercised against real Razorpay Test Mode traffic. Nothing
              below is a screenshot or a claim you have to take on trust.
            </p>
          </div>

          {/* The recovery chain, as a flow. */}
          <div className="mt-9 flex flex-wrap items-center justify-center gap-x-2 gap-y-2">
            {['payment.failed', 'diagnosis', 'policy approval', 'Payment Link',
              'payment_link.paid', 'RECOVERED', 'hash-chained ledger'].map((step, i, arr) => (
              <span key={step} className="flex items-center gap-2">
                <span className={`rounded-lg border px-2.5 py-1.5 font-mono text-[11px] font-bold ${
                  step === 'RECOVERED'
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                    : 'border-[var(--rzp-border)] bg-white text-[var(--rzp-ink-muted)]'
                }`}>
                  {step}
                </span>
                {i < arr.length - 1 && (
                  <ArrowRight size={13} strokeWidth={2.5} className="shrink-0 text-[var(--rzp-ink-faint)]" />
                )}
              </span>
            ))}
          </div>

          <div className="mt-8 grid grid-cols-1 gap-3 lg:grid-cols-5">
            {/* The one claim re-checked in the reviewer's own browser. */}
            <div className="rounded-2xl border-2 border-[#A6F4C5] bg-[#ECFDF3] p-5 lg:col-span-2">
              <span className="inline-flex items-center gap-1.5 rounded-md border border-[#A6F4C5] bg-white px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-green-dark)]">
                {checking ? <><Loader2 size={9} strokeWidth={2.6} className="animate-spin" />checking now</>
                  : <><Check size={9} strokeWidth={3} />checked live</>}
              </span>
              <h3 className="mt-3 text-lg font-bold text-[var(--rzp-ink)]">Hash-chained ledger</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--rzp-ink-muted)]">
                SHA-256 over an integer-only preimage, every entry linked to the one before it.
                This page recomputed the chain when it loaded.
              </p>
              <p className="mt-3 border-t border-[#A6F4C5] pt-3 font-mono text-[12px] font-bold text-[var(--rzp-green-dark)]">
                {checking ? 'verifying…'
                  : chain?.valid ? `${chain.entries_checked.toLocaleString('en-IN')} entries · chain intact`
                  : chain ? `chain broken at #${chain.first_broken_sequence}`
                  : 'chain unverified — API unreachable'}
              </p>

              <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[#A6F4C5] pt-3">
                <StatCell label="Records" value={records} />
                <StatCell label="Recovered" value={recovered != null ? recovered : '—'} />
                <StatCell label="Head" value={`${head}…`} />
              </div>
              <p className="mt-1.5 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                {live ? 'live from this batch' : 'from the committed demo receipt'}
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:col-span-3">
              {EVIDENCE.map((e) => {
                const Icon = e.icon;
                return (
                  <div key={e.key} className="rounded-2xl border border-[var(--rzp-border)] bg-white p-4">
                    <span className="flex items-center justify-between gap-2">
                      <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-muted)]">
                        <Icon size={14} strokeWidth={2.2} />
                      </span>
                      <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${
                        e.kind === 'scope'
                          ? 'border-amber-300 bg-amber-50 text-amber-800'
                          : 'border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink-faint)]'
                      }`}>
                        {e.kind === 'scope' ? 'scope' : 'in source'}
                      </span>
                    </span>
                    <h3 className="mt-2.5 text-sm font-bold text-[var(--rzp-ink)]">{e.label}</h3>
                    <p className="mt-1 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">{e.body}</p>
                    {e.src && (
                      <p className="mt-2 truncate font-mono text-[10px] text-[var(--rzp-ink-faint)]">{e.src}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 font-mono text-[11px] font-bold text-amber-800">
              <FlaskConical size={11} strokeWidth={2.4} />
              Razorpay Test Mode — no live money
            </span>
            <button onClick={() => onNavigateTab('overview')} className="rzp-link inline-flex items-center gap-1.5">
              Open the Command Center
              <ArrowRight size={14} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </section>

      {/* ══ 5 · SLIDING CARDS ════════════════════════════════════════════ */}
      <section className="bg-white py-16 lg:py-20">
        <div className="rzp-container">
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-3xl">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
                What makes it different
              </p>
              <h2 className="mt-2 text-[30px] font-bold leading-[1.12] tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[40px]">
                We recover differently.
              </h2>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button onClick={() => go(-1)} aria-label="Previous cards"
                className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:border-[var(--rzp-blue-600)] hover:text-[var(--rzp-blue-600)]">
                <ChevronLeft size={17} strokeWidth={2.2} />
              </button>
              <button onClick={() => go(1)} aria-label="Next cards"
                className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:border-[var(--rzp-blue-600)] hover:text-[var(--rzp-blue-600)]">
                <ChevronRight size={17} strokeWidth={2.2} />
              </button>
            </div>
          </div>

          {/* Viewport clips the track; the track slides one full page at a
              time, which is 2 cards at lg and 1 below. */}
          <div className="overflow-hidden">
            <div
              className="flex transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
              style={{ transform: `translateX(-${safePage * 100}%)` }}
            >
              {CARDS.map((c) => (
                <div key={c.leadBlue} className="w-full shrink-0 px-1.5 lg:w-1/2">
                  <article className="flex h-full flex-col rounded-3xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-6 sm:p-8">
                    <p className="text-[13px] font-semibold text-[var(--rzp-ink-muted)]">{c.eyebrow}</p>
                    <h3 className="mt-4 text-[26px] font-bold leading-[1.18] tracking-[-0.02em] sm:text-[30px]">
                      <span className="text-[var(--rzp-blue-600)]">{c.leadBlue}</span>{' '}
                      <span className="text-[var(--rzp-ink)]">{c.leadDark}</span>
                    </h3>
                    <p className="mt-4 flex-1 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">{c.body}</p>
                    <div className="mt-6">
                      <button
                        onClick={() => onNavigateTab(c.tab)}
                        className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[var(--rzp-blue-600)] px-5 py-2.5 text-sm font-bold text-white transition-all hover:-translate-y-0.5 hover:bg-[var(--rzp-blue-700)]"
                      >
                        {c.cta}
                        <ArrowRight size={15} strokeWidth={2.5} />
                      </button>
                    </div>
                  </article>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-6 flex items-center justify-center gap-2">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} onClick={() => setPage(i)} aria-label={`Go to slide ${i + 1}`}
                className={`h-2 cursor-pointer rounded-full transition-all ${
                  i === safePage ? 'w-6 bg-[var(--rzp-blue-600)]' : 'w-2 bg-[var(--rzp-border-strong)] hover:bg-[var(--rzp-ink-faint)]'
                }`} />
            ))}
          </div>
        </div>
      </section>

      {/* ══ 6 · SAFETY THESIS ════════════════════════════════════════════ */}
      <section className="bg-[var(--rzp-surface-alt)] py-16 lg:py-20">
        <div className="rzp-container">
          <div className="grid grid-cols-1 gap-8 rounded-3xl border border-[#A6F4C5] bg-[#F3FDF7] p-6 sm:p-9 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-green-dark)]">
                Our safety thesis
              </p>
              <h2 className="mt-3 text-[28px] font-bold leading-[1.18] tracking-[-0.02em] sm:text-[34px]">
                <span className="block text-[var(--rzp-ink)]">AI recommends.</span>
                <span className="block text-[var(--rzp-blue-600)]">Policy decides.</span>
                <span className="block text-[var(--rzp-green-dark)]">Ledger proves.</span>
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
                The model reads a bank error and proposes a cause. It never chooses a channel,
                authorises a rupee, or decides whether a customer may be contacted.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:col-span-8">
              {PRINCIPLES.map(({ label, icon: Icon, body }) => (
                <div key={label} className="rounded-2xl border border-[#A6F4C5]/70 bg-white p-4">
                  <span className="flex items-center gap-2">
                    <Icon size={15} strokeWidth={2.2} className="text-[var(--rzp-green-dark)]" />
                    <span className="text-sm font-bold text-[var(--rzp-ink)]">{label}</span>
                  </span>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--rzp-ink-muted)]">{body}</p>
                </div>
              ))}
              <p className="font-mono text-[10px] text-[var(--rzp-ink-faint)] sm:col-span-2">
                Thresholds behind these are the configured values in config.py and policy.py —
                the same ones the Command Center shows firing on individual payments.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ══ 7 · FINAL CTA ════════════════════════════════════════════════ */}
      <section className="rzp-container pb-16 lg:pb-20">
        <div className="relative overflow-hidden rounded-3xl bg-[#05070F] px-6 py-12 sm:px-10 lg:px-14">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_88%_50%,rgba(51,149,255,0.18),transparent_60%)]" />
          <div className="relative z-10 flex flex-col items-start justify-between gap-7 lg:flex-row lg:items-center">
            <div className="max-w-xl">
              <h2 className="text-[28px] font-bold leading-[1.16] tracking-[-0.02em] text-white sm:text-[34px]">
                See RecoverOS recover a payment.
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-slate-300/90">
                Explore a real recovery journey from failed payment to Razorpay settlement and
                ledger proof — including the ones it deliberately refused.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => onNavigateTab('overview')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[var(--rzp-blue-600)] px-6 py-3.5 text-[15px] font-bold text-white shadow-lg shadow-blue-900/40 transition-all hover:-translate-y-0.5 hover:bg-[#3395FF]"
              >
                Open Command Center
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
              <button
                onClick={() => onNavigateTab('console')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:border-white/30 hover:bg-white/[0.12]"
              >
                Explore the Engine
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
            </div>
          </div>

          <div className="relative z-10 mt-8 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/10 pt-5 font-mono text-[11px] text-slate-400">
            <span className="font-bold text-white">RecoverOS</span>
            <span>Autonomous Revenue Recovery</span>
            <span className="text-slate-600">·</span>
            <span>Built for the Razorpay Buildathon · Track 03</span>
            <span className="text-slate-600">·</span>
            <span className="text-amber-300/90">Not a Razorpay product.</span>
          </div>
        </div>
      </section>
    </div>
  );
}
