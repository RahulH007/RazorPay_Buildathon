/**
 * RecoverOS — About
 *
 * The closing argument. Home says what it is, the Command Center proves it
 * works, the Engine shows how a decision is made, Resources lets you inspect
 * the implementation — this page says why it was built this way, and hands the
 * reader back to the evidence.
 *
 * Three claims in the previous version were wrong and are gone: "React 18"
 * (package.json pins ^19.2.8), "Razorpay Blade" as the design system (this UI
 * is hand-rolled Tailwind over Razorpay-inspired CSS variables — Blade is
 * Razorpay's own library and is not a dependency here), and "Audit Inspector"
 * as a place to look (that component was removed; the audit trail now lives in
 * the Command Center's decision drawer). Every module named below was checked
 * against backend/app before it was written down.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import founderPhoto from '../../assets/founder.jpg';
import {
  ArrowRight,
  Ban,
  Bot,
  FlaskConical,
  GitBranch,
  Radar,
  ScrollText,
  ShieldCheck,
  Wallet,
} from 'lucide-react';

/* ── Section 2 · the thesis, as a sequence ─────────────────────────────── */
const THESIS = [
  {
    n: '01',
    label: 'AI recommends',
    icon: Bot,
    tone: 'violet',
    lead: 'It diagnoses the cause. It decides nothing.',
    body: 'A deterministic rule map handles known failure codes first, at no cost and with no model call. Gemini is asked only about codes the rules do not recognise, and returns a structured cause with a confidence score.',
    src: 'classifier.py · llm_agent.py',
  },
  {
    n: '02',
    label: 'Policy decides',
    icon: ShieldCheck,
    tone: 'blue',
    lead: 'Guardrails decide whether an action is allowed at all.',
    body: 'Consent, quiet hours, holdout control, attempt limits, cost ceiling and expected value are evaluated cheapest-first. The first refusal wins, so the recorded reason is the most fundamental one.',
    src: 'policy.py · guardrails.py · consent.py',
  },
  {
    n: '03',
    label: 'Ledger proves',
    icon: ScrollText,
    tone: 'emerald',
    lead: 'Every important decision leaves a record you can recompute.',
    body: 'Actions, refusals, spend and settlement transitions are appended to a hash-chained ledger. Verification walks the whole chain and names the first entry that fails.',
    src: 'ledger.py',
  },
];

const TONE = {
  violet: { chip: 'border-violet-200 bg-violet-50 text-violet-600', text: 'text-violet-700' },
  blue: { chip: 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)]', text: 'text-[var(--rzp-blue-600)]' },
  emerald: { chip: 'border-emerald-200 bg-emerald-50 text-emerald-600', text: 'text-[var(--rzp-green-dark)]' },
};

/* ── Section 3 · the engineering philosophy ────────────────────────────── */
const PRINCIPLES = [
  { icon: GitBranch, title: 'Rules before models',
    body: 'Known failure classes are matched deterministically before anything is asked of a model. The cheap, reproducible path handles the majority; the model is a fallback, not the front door.' },
  { icon: Ban, title: 'Stopping is a valid outcome',
    body: 'A recovery system that never declines is not restrained, it is indiscriminate. Refusals are first-class results here — written to the ledger with a reason code, exactly as sends are.' },
  { icon: Wallet, title: 'Economics are a policy',
    body: 'Expected value and accumulated spend constrain intervention. An attempt that costs more than the margin it can recover is refused outright, with the arithmetic recorded.' },
  { icon: ShieldCheck, title: 'Consent is a hard boundary',
    body: 'An opt-out suppresses future payments from the same contact, not just the one that triggered it. Quiet hours are enforced per channel, because a voice call at midnight is a different act from a message.' },
  { icon: FlaskConical, title: 'Controls need controls',
    body: 'A share of contacts is deliberately never contacted. Without an untreated arm, a recovery rate is a number about the world rather than a number about the system.' },
  { icon: ScrollText, title: 'Evidence over claims',
    body: 'A dashboard can assert anything. A hash chain cannot: change a recorded cost and verification names the entry by sequence number. The trail is the product as much as the recovery is.' },
];

/* ── Section 5 · what is actually built. Every module verified to exist ── */
const INVENTORY = [
  { area: 'Ingestion', body: 'Signed Razorpay webhook intake, normalised into a record',
    src: 'routes/webhooks.py · event_adapter.py' },
  { area: 'Diagnosis', body: 'Rule map first, model fallback with a confidence threshold, cached replay',
    src: 'classifier.py · llm_agent.py · llm_cache.py' },
  { area: 'Policy', body: 'Nine refusal reason codes, consent registry, attempt and cost guardrails',
    src: 'policy.py · guardrails.py · consent.py' },
  { area: 'Recovery actions', body: 'Silent retry, WhatsApp link, UPI re-sequence, Hinglish voice, human queue',
    src: 'recovery_actions.py · voice_pipeline.py' },
  { area: 'Settlement', body: 'Razorpay Test Mode Payment Links, correlated and applied exactly once',
    src: 'settlement.py · razorpay_client.py · models.py' },
  { area: 'State', body: 'Transitions and outcome simulation for the seeded batch',
    src: 'state_machine.py · outcome_engine.py' },
  { area: 'Evidence', body: 'SHA-256 hash chain over an integer-only preimage, with chain verification',
    src: 'ledger.py' },
  { area: 'Real-time', body: 'Batch progress and state changes streamed to the dashboard',
    src: 'websocket_manager.py · /ws/dashboard' },
];


export default function AboutRahulView({ onNavigateTab }) {
  return (
    <div className="space-y-16 pb-4 lg:space-y-20">
      {/* ══ 1 · HERO ═══════════════════════════════════════════════════ */}
      <section>
        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
          The closing argument
        </p>
        <h1 className="mt-3 max-w-3xl text-[34px] font-bold leading-[1.1] tracking-[-0.025em] text-[var(--rzp-ink)] sm:text-[44px]">
          Why we built RecoverOS
        </h1>

        <div className="mt-6 grid grid-cols-1 gap-8 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <p className="text-base leading-relaxed text-[var(--rzp-ink-muted)]">
              A failed payment is not a retry problem. Retrying is the easy part — and the part
              that gets a merchant reported as spam.
            </p>
            <p className="mt-4 text-base leading-relaxed text-[var(--rzp-ink-muted)]">
              A recovery system has to work out <em>why</em> a payment failed, decide whether
              recovery is appropriate at all, choose an action proportionate to what is being
              recovered, respect consent and economic limits — and leave a record of what it did
              that someone else can check. Most of that is judgement, and judgement is exactly
              what you should not hand to a model without a boundary.
            </p>
            <p className="mt-4 text-base leading-relaxed text-[var(--rzp-ink-muted)]">
              So the boundary is the product. RecoverOS separates the part that reads a bank
              error from the part that is allowed to spend money, and writes both down.
            </p>
          </div>

          {/* The thesis, stated once and given its own weight. */}
          <div className="lg:col-span-5">
            <div className="rounded-3xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-6 sm:p-7">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-ink-faint)]">
                The thesis
              </p>
              <p className="mt-4 text-[26px] font-bold leading-[1.24] tracking-[-0.02em] sm:text-[30px]">
                <span className="block text-violet-700">AI recommends.</span>
                <span className="block text-[var(--rzp-blue-600)]">Policy decides.</span>
                <span className="block text-[var(--rzp-green-dark)]">Ledger proves.</span>
              </p>
              <p className="mt-4 border-t border-[var(--rzp-border)] pt-4 text-xs leading-relaxed text-[var(--rzp-ink-muted)]">
                Three sentences, three separate subsystems. The model never picks a channel or
                authorises a rupee; the policy engine never invents a diagnosis; the ledger
                argues with both if either is edited after the fact.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ══ 2 · THE THESIS, IN SEQUENCE ════════════════════════════════ */}
      <section>
        <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-[26px] font-bold leading-tight tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[32px]">
            Three responsibilities, kept apart.
          </h2>
          <button
            onClick={() => onNavigateTab?.('console')}
            className="rzp-link inline-flex items-center gap-1.5"
          >
            See this run on a real payment
            <ArrowRight size={14} strokeWidth={2.5} />
          </button>
        </div>

        <ol className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {THESIS.map((t) => {
            const Icon = t.icon;
            const tone = TONE[t.tone];
            return (
              <li key={t.n} className="flex flex-col rounded-2xl border border-[var(--rzp-border)] bg-white p-6">
                <div className="flex items-center justify-between">
                  <span className={`flex h-10 w-10 items-center justify-center rounded-xl border ${tone.chip}`}>
                    <Icon size={17} strokeWidth={2.2} />
                  </span>
                  <span className="font-mono text-[11px] font-bold text-[var(--rzp-ink-faint)]">{t.n}</span>
                </div>
                <h3 className={`mt-4 text-base font-bold uppercase tracking-wide ${tone.text}`}>{t.label}</h3>
                <p className="mt-2 text-sm font-semibold leading-snug text-[var(--rzp-ink)]">{t.lead}</p>
                <p className="mt-2 flex-1 text-[12px] leading-relaxed text-[var(--rzp-ink-muted)]">{t.body}</p>
                <p className="mt-4 truncate border-t border-[var(--rzp-border)] pt-3 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                  {t.src}
                </p>
              </li>
            );
          })}
        </ol>
      </section>

      {/* ══ 3 · WHY THIS APPROACH ══════════════════════════════════════ */}
      <section>
        <div className="mb-7 max-w-2xl">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
            Engineering philosophy
          </p>
          <h2 className="mt-2 text-[26px] font-bold leading-tight tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[32px]">
            Why this approach.
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PRINCIPLES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-2xl border border-[var(--rzp-border)] bg-white p-5 transition-colors hover:border-[var(--rzp-border-strong)]">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] text-[var(--rzp-blue-600)]">
                <Icon size={15} strokeWidth={2.2} />
              </span>
              <h3 className="mt-3.5 text-[15px] font-bold text-[var(--rzp-ink)]">{title}</h3>
              <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--rzp-ink-muted)]">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══ 4 · BUILDER STORY ══════════════════════════════════════════ */}
      <section>
        <div className="grid grid-cols-1 gap-7 rounded-3xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-6 sm:p-8 lg:grid-cols-12">
          <div className="lg:col-span-3">
            {/* The real portrait rather than a monogram — the same asset the
                Home hero uses, so there is one picture of the builder in the
                product and not two different placeholders. */}
            <div className="w-full max-w-[220px] overflow-hidden rounded-2xl border border-[var(--rzp-border)] bg-white shadow-sm">
              <img
                src={founderPhoto}
                alt="Rahul Hongekar, builder of RecoverOS"
                className="aspect-square w-full object-cover object-[center_20%]"
                loading="lazy"
                decoding="async"
              />
            </div>

            <h2 className="mt-4 text-xl font-extrabold tracking-tight text-[var(--rzp-ink)]">
              Rahul Hongekar
            </h2>
            <p className="mt-0.5 text-xs text-[var(--rzp-ink-muted)]">Architect of RecoverOS</p>


            <a
              href="https://github.com/RahulH007"
              target="_blank"
              rel="noreferrer"
              className="mt-4 block font-mono text-[11px] text-[var(--rzp-ink-faint)] transition-colors hover:text-[var(--rzp-blue-600)]"
            >
              github.com/RahulH007 ↗
            </a>
          </div>

          <div className="lg:col-span-9">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-ink-faint)]">
              Builder’s note
            </p>

            <p className="mt-3 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
              The interesting thing about failed online checkouts in India was never the volume —
              it was that the obvious fix makes the problem worse. Retry harder, message more, and
              you convert a payments problem into a trust problem.
            </p>
            <p className="mt-3.5 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
              That reframes it as a decision system rather than a retry system, and a decision
              system is only as good as its constraints. So the design started from the refusals:
              what should stop this, and how would anyone know it stopped for the right reason?
              The escalation ladder, the cost ceiling and the holdout arm all fell out of that
              question rather than being added to it.
            </p>
            <p className="mt-3.5 text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
              Provenance is the same instinct applied to the output. Anything touching money
              should be able to show its work — so every action, every refusal and every rupee
              spent is written to a hash-chained ledger a reviewer can verify independently, and
              the interface is built to hand that evidence over rather than ask to be believed.
            </p>

          </div>
        </div>
      </section>

      {/* ══ 5 · WHAT IS ACTUALLY BUILT ═════════════════════════════════ */}
      <section>
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div className="max-w-2xl">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--rzp-blue-600)]">
              Inventory
            </p>
            <h2 className="mt-2 text-[26px] font-bold leading-tight tracking-[-0.02em] text-[var(--rzp-ink)] sm:text-[32px]">
              What is actually built.
            </h2>
          </div>
          <button
            onClick={() => onNavigateTab?.('docs')}
            className="rzp-link inline-flex items-center gap-1.5"
          >
            Read the implementation
            <ArrowRight size={14} strokeWidth={2.5} />
          </button>
        </div>

        <div className="overflow-hidden rounded-2xl border border-[var(--rzp-border)] bg-white">
          {INVENTORY.map(({ area, body, src }, i) => (
            <div
              key={area}
              className={`flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-3.5 ${
                i > 0 ? 'border-t border-[var(--rzp-border)]' : ''
              }`}
            >
              <span className="w-32 shrink-0 text-[13px] font-bold text-[var(--rzp-ink)]">{area}</span>
              <span className="min-w-[220px] flex-1 text-[12px] leading-relaxed text-[var(--rzp-ink-muted)]">{body}</span>
              <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">{src}</span>
            </div>
          ))}
        </div>

        <p className="mt-3 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
          Every module named above exists under backend/app. Nothing is aspirational.
        </p>
      </section>

      {/* ══ 6 · FINAL CTA ══════════════════════════════════════════════ */}
      <section>
        <div className="relative overflow-hidden rounded-3xl bg-[#05070F] px-6 py-12 sm:px-10">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_88%_40%,rgba(51,149,255,0.18),transparent_62%)]" />
          <div className="relative z-10">
            <h2 className="max-w-2xl text-[28px] font-bold leading-[1.14] tracking-[-0.02em] text-white sm:text-[34px]">
              Don’t take our word for it.
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-300/90">
              Follow the decision, inspect the policy, and verify the ledger.
            </p>

            <div className="mt-7 flex flex-wrap items-center gap-3">
              <button
                onClick={() => onNavigateTab?.('overview')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[var(--rzp-blue-600)] px-6 py-3.5 text-[15px] font-bold text-white shadow-lg shadow-blue-900/40 transition-all hover:-translate-y-0.5 hover:bg-[#3395FF]"
              >
                Explore Command Center
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
              <button
                onClick={() => onNavigateTab?.('console')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:border-white/30 hover:bg-white/[0.12]"
              >
                Walk through the Engine
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
              <button
                onClick={() => onNavigateTab?.('docs')}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:border-white/30 hover:bg-white/[0.12]"
              >
                Inspect Resources
                <ArrowRight size={16} strokeWidth={2.5} />
              </button>
            </div>

            <div className="mt-8 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/10 pt-5 font-mono text-[11px] text-slate-400">
              <Radar size={12} strokeWidth={2.2} className="text-slate-500" />
              <span className="font-bold text-white">RecoverOS</span>
              <span>Autonomous Revenue Recovery</span>
              <span className="text-slate-600">·</span>
              <span>Razorpay Buildathon · Track 03</span>
              <span className="text-slate-600">·</span>
              <span className="text-amber-300/90">Not a Razorpay product.</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
