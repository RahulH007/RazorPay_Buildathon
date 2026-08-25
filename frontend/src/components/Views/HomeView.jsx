import { useState } from 'react';
import founderPhoto from '../../assets/founder.jpg';
import { 
  ArrowRight, 
  ChevronLeft, 
  ChevronRight, 
  Globe, 
  Zap, 
  ShieldCheck, 
  CreditCard, 
  Sparkles, 
  PhoneCall, 
  MessageCircle,
  Pencil,
  ArrowUpRight
} from 'lucide-react';

export default function HomeView({ onNavigateTab, onRunBatch, metrics }) {
  const [heroSlide, setHeroSlide] = useState(0);

  const SLIDES = [
    {
      titleBlue: "Effortless Revenue Recovery",
      titleDark: "for founders defying all odds",
      subline: "Powerful Automation | Smart AI Diagnostics | Integrated Fallback Access",
    },
    {
      titleBlue: "Autonomous Fallback Routing",
      titleDark: "engineered for zero churn",
      subline: "NPCI Throttles Intercepted | Instant WhatsApp UPI | Cryptographic Audit",
    }
  ];

  const current = SLIDES[heroSlide % SLIDES.length];

  return (
    <div className="space-y-0 font-sans">

      {/* ═══════════════════════════════════════════════════════════════
          HERO SECTION — Matches razorpay.com Homepage Screenshot 1
          White/light gradient bg, left-aligned headline, right visual card
          ═══════════════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden bg-white">

        {/* Razorpay's hero carries a soft blue wash behind the visual, not a
            bordered card. Kept faint so the headline stays the focal point. */}
        <div className="pointer-events-none absolute right-0 top-0 h-full w-3/5 bg-[linear-gradient(to_left,#E4EEFD_0%,#EFF5FE_35%,rgba(244,248,255,0.45)_65%,transparent_100%)]" />

        <div className="rzp-container relative z-10 grid grid-cols-1 items-center gap-10 py-16 lg:grid-cols-12 lg:py-20">
          
          {/* ── LEFT: Headline, Subline, CTAs, Arrows ── */}
          <div className="lg:col-span-7">
            <h1 className="text-[40px] font-bold leading-[1.1] tracking-[-0.02em] sm:text-[52px] lg:text-[60px]">
              <span className="block text-[var(--rzp-blue-600)]">{current.titleBlue}</span>
              <span className="mt-1 block text-[var(--rzp-ink)]">{current.titleDark}</span>
            </h1>

            <p className="mt-6 text-base font-medium text-[var(--rzp-ink-muted)]">
              {current.subline}
            </p>

            {/* CTAs — Blue filled "Sign Up Now" + text "Know More" */}
            <div className="mt-8 flex items-center gap-6">
              <button onClick={() => onNavigateTab('overview')} className="rzp-btn-primary px-7 py-3 text-[15px]">
                Sign Up Now
              </button>
              <button onClick={() => onNavigateTab('docs')} className="rzp-link text-[15px]">
                Know More
              </button>
            </div>

          </div>

          {/* ── RIGHT: Visual card ──
              The brand block and the status pills previously both used
              absolute positioning and collided at this aspect ratio. They now
              occupy separate rows of a flex column, so nothing can overlap
              regardless of how many pills a slide carries. */}
          <div className="lg:col-span-5">
            <div className="relative mx-auto flex aspect-[4/5] w-full max-w-[400px] flex-col overflow-hidden rounded-3xl bg-gradient-to-b from-[#1B3A6B] via-[#2456B8] to-[#3B82F6] p-6 shadow-[0_24px_60px_rgba(22,47,86,0.28)]">

              {/* The photo is the visual. Everything that used to float over it -
                  a product badge and three invented status pills - claimed
                  things the system does not do, so it is gone. */}
              <div className="absolute inset-0 overflow-hidden">
                <img
                  src={founderPhoto}
                  alt="Rahul, builder of RecoverOS"
                  className="h-full w-full object-cover object-[center_18%]"
                  loading="eager"
                  decoding="async"
                />
                {/* Brand wash plus a bottom fade so the attribution stays legible */}
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#1B3A6B]/35 via-transparent to-[#1B3A6B]/15" />
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-[#0C2451]/85 via-[#0C2451]/30 to-transparent" />
              </div>

              {/* Attribution, bottom left - links through to the About page */}
              <button
                onClick={() => onNavigateTab('about')}
                className="absolute bottom-6 left-6 z-10 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-white/20 bg-[#0C2451]/75 px-4 py-2 text-xs font-bold text-white shadow-lg backdrop-blur-lg transition-colors hover:bg-[#0C2451]/90"
              >
                <span>Rahul</span>
                <span className="text-[11px] font-normal text-cyan-200">Builder</span>
                <ArrowUpRight size={12} strokeWidth={2.5} className="text-cyan-200" />
              </button>
            </div>

            {/* Carousel arrows sit under the visual, as on razorpay.com */}
            <div className="mt-6 flex items-center justify-center gap-3">
              <button
                onClick={() => setHeroSlide(prev => (prev === 0 ? SLIDES.length - 1 : prev - 1))}
                className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)]"
                aria-label="Previous slide"
              >
                <ChevronLeft size={16} strokeWidth={2} />
              </button>
              <button
                onClick={() => setHeroSlide(prev => prev + 1)}
                className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border border-[var(--rzp-border-strong)] bg-white text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)]"
                aria-label="Next slide"
              >
                <ChevronRight size={16} strokeWidth={2} />
              </button>
            </div>
          </div>
        </div>

        {/* ── BOTTOM: Recommendation pill bar (matches Razorpay screenshot 1 exactly) ── */}
        <div className="rzp-container relative z-10 pb-10 pt-2">
          <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar pb-1 text-xs font-semibold">
            <div className="flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-[#1B1F36] text-white shrink-0 font-bold shadow-sm">
              <Sparkles size={13} className="text-emerald-400" />
              <span>Get recommendations</span>
            </div>

            {[
              { icon: CreditCard, label: 'Accept Payments', tab: 'overview' },
              { icon: MessageCircle, label: 'WhatsApp Recovery', tab: 'overview' },
              { icon: Zap, label: 'Start Business Banking', tab: 'overview' },
              { icon: PhoneCall, label: 'Voice IVR Rail', tab: 'console' },
              { icon: ShieldCheck, label: 'Fraud Quarantine', tab: 'overview' },
            ].map(({ icon: PillIcon, label, tab }, i) => (
              <button 
                key={i}
                onClick={() => onNavigateTab(tab)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white hover:bg-blue-50 border border-slate-200 text-[var(--rzp-blue-600)] shrink-0 transition-colors cursor-pointer shadow-xs"
              >
                <PillIcon size={13} />
                <span>{label}</span>
              </button>
            ))}

            <button 
              onClick={() => onNavigateTab('docs')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white hover:bg-slate-50 border border-slate-200 text-[var(--rzp-ink-muted)] shrink-0 transition-colors cursor-pointer shadow-xs"
            >
              <Pencil size={13} />
              <span>Something else?</span>
            </button>
          </div>
        </div>
      </section>


      {/* ═══════════════════════════════════════════════════════════════
          DISRUPTION SECTION — Matches razorpay.com Screenshot 2
          Dark bold heading + two white elevated cards on #F7F8FA bg
          ═══════════════════════════════════════════════════════════════ */}
      <section className="rzp-container mt-16 space-y-10 pb-20">
        <h2 className="text-[32px] sm:text-[38px] lg:text-[42px] font-extrabold text-[var(--rzp-ink)] tracking-tight leading-tight">
          We have innovated at every instance, creating a disruption.
        </h2>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
          
          {/* Card 1: MoneySaver / AI Diagnostic (Large — col-span-7) */}
          <div className="lg:col-span-7 rounded-2xl bg-white border border-slate-200/80 p-8 sm:p-10 shadow-[0_2px_20px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_30px_rgba(0,0,0,0.08)] transition-shadow duration-300 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--rzp-ink-muted)] mb-7">
                <span className="tracking-wide">MoneySaver Export Account</span>
                <Globe size={22} className="text-[var(--rzp-ink)]" />
              </div>

              <h3 className="text-[26px] sm:text-[30px] lg:text-[34px] font-extrabold text-[var(--rzp-ink)] leading-[1.2] tracking-tight">
                <span className="text-[var(--rzp-blue-600)]">Open a virtual account in 200+ countries, </span>
                save up to 50% on international bank transfer charges. Receive ACH/SWIFT/SEPA/BACS payments
              </h3>

              <p className="mt-8 text-sm text-[var(--rzp-ink-muted)] font-medium leading-relaxed">
                Receive international wire transfers with ease with a smart account
              </p>
            </div>

            <div className="flex items-center gap-5 pt-8">
              <button 
                onClick={() => onNavigateTab('overview')}
                className="flex items-center gap-2 px-5 py-3 rounded-lg bg-[var(--rzp-blue-600)] hover:bg-[var(--rzp-blue-700)] text-white text-sm font-bold shadow-md shadow-blue-500/20 transition-all cursor-pointer"
              >
                <span>Sign Up</span>
                <ArrowRight size={14} strokeWidth={2.5} />
              </button>
              <button 
                onClick={() => onNavigateTab('docs')}
                className="text-[var(--rzp-ink)] hover:text-[var(--rzp-blue-600)] text-sm font-bold hover:underline cursor-pointer"
              >
                Know More
              </button>
            </div>
          </div>

          {/* Card 2: Turbo UPI / Recovery (Smaller — col-span-5) */}
          <div className="lg:col-span-5 relative rounded-2xl bg-white border border-slate-200/80 p-8 sm:p-10 shadow-[0_2px_20px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_30px_rgba(0,0,0,0.08)] transition-shadow duration-300 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--rzp-ink-muted)] mb-7">
                <span className="tracking-wide">Turbo UPI</span>
                <Zap size={22} className="text-[var(--rzp-ink)]" />
              </div>

              <h3 className="text-[22px] sm:text-[26px] font-extrabold text-[var(--rzp-ink)] leading-[1.2] tracking-tight">
                <span className="text-[var(--rzp-blue-600)]">Experience a 5X faster checkout, </span>
                achieve a 10% success rate boost, all without any redirections to UPI apps.
              </h3>

              <p className="mt-8 text-xs sm:text-sm text-[var(--rzp-ink-muted)] font-medium leading-relaxed">
                Get India's fastest one-step UPI payment solution for businesses
              </p>
            </div>

            <div className="flex items-center gap-5 pt-8">
              <button 
                onClick={() => onNavigateTab('overview')}
                className="flex items-center gap-2 px-5 py-3 rounded-lg bg-[var(--rzp-blue-600)] hover:bg-[var(--rzp-blue-700)] text-white text-sm font-bold shadow-md shadow-blue-500/20 transition-all cursor-pointer"
              >
                <span>Sign Up</span>
                <ArrowRight size={14} strokeWidth={2.5} />
              </button>
              <button 
                onClick={() => onNavigateTab('docs')}
                className="text-[var(--rzp-ink)] hover:text-[var(--rzp-blue-600)] text-sm font-bold hover:underline cursor-pointer"
              >
                Know More
              </button>
            </div>

            {/* Floating carousel circle arrow (right edge, matching Razorpay) */}
            <div className="hidden lg:flex absolute -right-4 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-[var(--rzp-blue-600)] text-white items-center justify-center shadow-lg cursor-pointer hover:scale-110 transition-transform z-10">
              <ChevronRight size={18} strokeWidth={2.5} />
            </div>
          </div>

        </div>
      </section>

      {/* Bottom padding */}
      <div className="h-20" />
    </div>
  );
}
