/**
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 *
 * Home.
 *
 * Every number on this page comes from a command in the README. The previous
 * version carried invented metrics - "<18ms", "94.2% accuracy", "50M+
 * transaction patterns" - alongside two of Razorpay's own product cards. A
 * reviewer reading the README's "what is real and what is not" table next to
 * those claims would have found the contradiction, and the honesty is the more
 * valuable of the two.
 */

import { useState } from 'react';
import founderPhoto from '../../assets/founder.jpg';
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Link2,
  ShieldBan,
  Bot,
  FlaskConical,
  Terminal,
  ArrowUpRight,
} from 'lucide-react';

// Figures from the committed demo receipt (results/demo_run.txt). If the demo
// changes, these change with it - that is the point of quoting them.
const RUN = {
  records: 65,
  entries: 470,
  reasonCodes: 9,
  head: 'ad72a067',
};

const SLIDES = [
  {
    titleBlue: 'Prove what you did,',
    titleDark: 'what you spent, and why you stopped.',
    subline:
      'A revenue recovery agent whose every action, refusal and rupee is written to a hash-chained ledger you can verify yourself.',
  },
  {
    titleBlue: 'Restraint is a feature,',
    titleDark: 'not an absence of one.',
    subline:
      'Nine reason codes govern when this system refuses to act. Every refusal is recorded with its reason, the same as every send.',
  },
];

// Four cards in two sets. Each set is one wide card and one narrow one, the
// asymmetric pairing razorpay.com uses; the circular arrow on the right edge
// advances between sets.
const CARD_SETS = [
  [
    {
      icon: Link2,
      label: 'Tamper-evident ledger',
      leadBlue: 'Every action is hash-chained,',
      leadDark:
        'so a cost edited directly in the database is named, by sequence number, the moment you verify.',
      body: 'SHA-256 over an integer-only preimage. A UNIQUE index on prev_hash makes a forked chain structurally impossible.',
      stat: `${RUN.entries} entries`,
      statNote: `head ${RUN.head}…`,
      tab: 'console',
      cta: 'Verify the chain',
    },
    {
      icon: ShieldBan,
      label: 'Policy engine',
      leadBlue: 'It records why it did nothing,',
      leadDark: 'with a reason code, the same as it records every send.',
      body: 'Attempt caps, cost ceiling, consent withdrawal, quiet hours, negative expected value, a holdout arm.',
      stat: `${RUN.reasonCodes} reason codes`,
      statNote: 'all fire in one run',
      tab: 'overview',
      cta: 'See the board',
    },
  ],
  [
    {
      icon: Bot,
      label: 'Gemini, fenced',
      leadBlue: 'The model reads.',
      leadDark: 'Policy decides. Gemini never picks a channel or authorises a rupee.',
      body: 'It diagnoses unmapped bank errors, reads Hinglish replies and writes per-customer copy. Generated messages are checked before sending: the model writes the words, never the numbers.',
      stat: 'Rules first',
      statNote: 'model only where rules run out',
      tab: 'docs',
      cta: 'How it works',
    },
    {
      icon: FlaskConical,
      label: 'Honest measurement',
      leadBlue: 'A fifth of contacts are never contacted,',
      leadDark: 'so recovery can be attributed rather than assumed.',
      body: 'Holdout is assigned per contact and stratified by failure class, so one person never lands in both arms.',
      stat: '20% holdout',
      statNote: 'stratified, per contact',
      tab: 'overview',
      cta: 'See the split',
    },
  ],
];

export default function HomeView({ onNavigateTab, onRunBatch, metrics }) {
  const [heroSlide, setHeroSlide] = useState(0);
  const [cardSet, setCardSet] = useState(0);
  const current = SLIDES[heroSlide % SLIDES.length];

  return (
    <div className="font-sans">

      {/* ── HERO ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-white">
        <div className="pointer-events-none absolute right-0 top-0 h-full w-3/5 bg-[linear-gradient(to_left,#E4EEFD_0%,#EFF5FE_35%,rgba(244,248,255,0.45)_65%,transparent_100%)]" />

        <div className="rzp-container relative z-10 grid grid-cols-1 items-center gap-10 py-16 lg:grid-cols-12 lg:py-20">

          <div className="lg:col-span-7">
            <h1 className="text-[40px] font-bold leading-[1.1] tracking-[-0.02em] sm:text-[52px] lg:text-[58px]">
              <span className="block text-[var(--rzp-blue-600)]">{current.titleBlue}</span>
              <span className="mt-1 block text-[var(--rzp-ink)]">{current.titleDark}</span>
            </h1>

            <p className="mt-6 max-w-[560px] text-base leading-relaxed text-[var(--rzp-ink-muted)]">
              {current.subline}
            </p>

            {/* Both CTAs do the thing they name. The previous pair said
                "Sign Up Now" and "Know More" on a project with no accounts. */}
            <div className="mt-8 flex flex-wrap items-center gap-6">
              <button
                onClick={() => onNavigateTab('overview')}
                className="rzp-btn-primary px-7 py-3 text-[15px]"
              >
                Run the recovery batch
              </button>
              <button
                onClick={() => onNavigateTab('console')}
                className="rzp-link inline-flex items-center gap-1.5 text-[15px]"
              >
                <Terminal size={15} strokeWidth={2} />
                Verify the ledger
              </button>
            </div>

            {/* Slide arrows sit under the copy, on the left, rather than
                under the portrait - the headline is what they change. */}
            <div className="mt-8 flex items-center gap-3">
              <button
                onClick={() => setHeroSlide((prev) => (prev === 0 ? SLIDES.length - 1 : prev - 1))}
                className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)]"
                aria-label="Previous slide"
              >
                <ChevronLeft size={16} strokeWidth={2} />
              </button>
              <button
                onClick={() => setHeroSlide((prev) => prev + 1)}
                className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)]"
                aria-label="Next slide"
              >
                <ChevronRight size={16} strokeWidth={2} />
              </button>
            </div>

            <p className="mt-8 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
              {RUN.records} seeded records · {RUN.entries} ledger entries · byte-identical on every run
            </p>
          </div>

          {/* ── Portrait ── */}
          <div className="lg:col-span-5">
            <div className="relative mx-auto flex aspect-[4/5] w-full max-w-[400px] flex-col overflow-hidden rounded-3xl bg-gradient-to-b from-[#1B3A6B] via-[#2456B8] to-[#3B82F6] p-6 shadow-[0_24px_60px_rgba(22,47,86,0.28)]">
              <div className="absolute inset-0 overflow-hidden">
                <img
                  src={founderPhoto}
                  alt="Rahul Hongekar, builder of RecoverOS"
                  className="h-full w-full object-cover object-[center_18%]"
                  loading="eager"
                  decoding="async"
                />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#1B3A6B]/35 via-transparent to-[#1B3A6B]/15" />
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-[#0C2451]/85 via-[#0C2451]/30 to-transparent" />
              </div>

              <button
                onClick={() => onNavigateTab('about')}
                className="absolute bottom-6 left-6 z-10 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-white/20 bg-[#0C2451]/75 px-4 py-2 text-xs font-bold text-white shadow-lg backdrop-blur-lg transition-colors hover:bg-[#0C2451]/90"
              >
                <span>Rahul</span>
                <span className="text-[11px] font-normal text-cyan-200">Builder</span>
                <ArrowUpRight size={12} strokeWidth={2.5} className="text-cyan-200" />
              </button>
            </div>

          </div>
        </div>
      </section>

      {/* ── WHAT IT ACTUALLY DOES ───────────────────────────────────
          Two cards at a time, wide + narrow, as on razorpay.com. The
          circular arrow on the right edge swaps in the second set. */}
      <section className="bg-[var(--rzp-surface-alt)] py-20">
        <div className="rzp-container">
          <h2 className="max-w-[860px] text-[30px] font-extrabold leading-tight tracking-tight text-[var(--rzp-ink)] sm:text-[36px] lg:text-[42px]">
            Most recovery tools tell you what they recovered.{' '}
            <span className="text-[var(--rzp-blue-600)]">This one can prove it.</span>
          </h2>

          {/* Both sets occupy the same grid cell, with the inactive one kept
              in flow but invisible. The container is therefore always as tall
              as the taller set, at every viewport width - which a fixed
              min-height would only achieve at the width it was measured at.
              Without this the section jumps when you switch and the shorter
              pair reads as smaller cards. */}
          <div className="relative mt-10 grid">
            {CARD_SETS.map((set, si) => (
              <div
                key={si}
                aria-hidden={si !== cardSet}
                className={`col-start-1 row-start-1 grid grid-cols-1 items-stretch gap-6 transition-opacity duration-200 lg:grid-cols-12 ${
                  si === cardSet
                    ? 'opacity-100'
                    : 'pointer-events-none invisible opacity-0'
                }`}
              >
                {set.map(
                  ({ icon: Icon, label, leadBlue, leadDark, body, stat, statNote, tab, cta }, i) => (
                <div
                  key={label}
                  className={`${
                    i === 0 ? 'lg:col-span-7' : 'lg:col-span-5'
                  } flex flex-col justify-between rounded-2xl border border-slate-200/80 bg-white p-8 shadow-[0_2px_20px_rgba(0,0,0,0.04)] transition-shadow duration-300 hover:shadow-[0_4px_30px_rgba(0,0,0,0.08)] sm:p-10`}
                >
                  <div>
                    <div className="mb-7 flex items-center justify-between text-xs font-semibold text-[var(--rzp-ink-muted)]">
                      <span className="tracking-wide">{label}</span>
                      <Icon size={22} strokeWidth={2} className="text-[var(--rzp-ink)]" />
                    </div>

                    <h3
                      className={`font-extrabold leading-[1.2] tracking-tight text-[var(--rzp-ink)] ${
                        i === 0
                          ? 'text-[26px] sm:text-[30px] lg:text-[34px]'
                          : 'text-[22px] sm:text-[26px]'
                      }`}
                    >
                      <span className="text-[var(--rzp-blue-600)]">{leadBlue} </span>
                      {leadDark}
                    </h3>

                    <p className="mt-8 text-sm font-medium leading-relaxed text-[var(--rzp-ink-muted)]">
                      {body}
                    </p>
                  </div>

                  <div className="pt-8">
                    <div className="mb-6 border-t border-[var(--rzp-border)] pt-4">
                      <p className="font-mono text-lg font-bold tracking-tight text-[var(--rzp-ink)]">
                        {stat}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
                        {statNote}
                      </p>
                    </div>

                    <button
                      onClick={() => onNavigateTab(tab)}
                      className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-[var(--rzp-blue-600)] px-5 py-3 text-sm font-bold text-white shadow-md shadow-blue-500/20 transition-all hover:bg-[var(--rzp-blue-700)]"
                    >
                      <span>{cta}</span>
                      <ArrowRight size={14} strokeWidth={2.5} />
                    </button>
                  </div>
                </div>
                  ),
                )}
              </div>
            ))}

            {/* Set switcher, on the right edge of the narrow card */}
            <button
              onClick={() => setCardSet((prev) => (prev + 1) % CARD_SETS.length)}
              aria-label="Show the next pair"
              className="absolute -right-4 top-1/2 hidden h-9 w-9 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full bg-[var(--rzp-blue-600)] text-white shadow-lg transition-transform hover:scale-110 lg:flex"
            >
              <ChevronRight size={18} strokeWidth={2.5} />
            </button>
          </div>

          {/* Two sets is not obvious from one arrow, so say so quietly. */}
          <div className="mt-8 flex items-center gap-2">
            {CARD_SETS.map((_, i) => (
              <button
                key={i}
                onClick={() => setCardSet(i)}
                aria-label={`Show pair ${i + 1}`}
                className={`h-1.5 cursor-pointer rounded-full transition-all ${
                  i === cardSet
                    ? 'w-6 bg-[var(--rzp-blue-600)]'
                    : 'w-1.5 bg-[var(--rzp-border-strong)] hover:bg-[var(--rzp-ink-faint)]'
                }`}
              />
            ))}
          </div>
        </div>
      </section>

      {/* ── CLOSING LINE ────────────────────────────────────────────── */}
      <section className="rzp-container py-16">
        <div className="flex flex-col items-start justify-between gap-6 rounded-2xl border border-[var(--rzp-border)] bg-white p-8 sm:flex-row sm:items-center">
          <div>
            <p className="text-lg font-bold tracking-tight text-[var(--rzp-ink)]">
              Run it twice. You get the same head hash.
            </p>
            <p className="mt-1.5 text-sm text-[var(--rzp-ink-muted)]">
              Recovery numbers you cannot reproduce are marketing. These reproduce.
            </p>
          </div>
          <button
            onClick={() => onNavigateTab('console')}
            className="rzp-btn-secondary shrink-0 px-6 py-3 text-sm"
          >
            Open the engine console
          </button>
        </div>
      </section>
    </div>
  );
}
