import { useState } from 'react';
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
  Pencil
} from 'lucide-react';

export default function HomeView({ onNavigateTab, onRunBatch, metrics }) {
  const [heroSlide, setHeroSlide] = useState(0);

  const SLIDES = [
    {
      titleBlue: "Effortless Revenue Recovery",
      titleDark: "for founders defying all odds",
      subline: "Powerful Automation | Smart AI Diagnostics | Integrated Fallback Access",
      founderName: "Rahul",
      founderRole: "Lead Architect ↗",
      productBadge: "COMET / RAY AI",
      productSub: "POWERED BY RAZORPAY RECOVERY ENGINE",
      pills: [
        { label: "Vendors Paid", value: "₹4,990 Reclaimed" },
        { label: "ERP Updated", value: "14ms AI Diagnosis" },
        { label: "Corporate Card Issued", value: "" }
      ]
    },
    {
      titleBlue: "Autonomous Fallback Routing",
      titleDark: "engineered for zero churn",
      subline: "NPCI Throttles Intercepted | Instant WhatsApp UPI | Cryptographic Audit",
      founderName: "RecoverOS",
      founderRole: "AI Foundation Engine ↗",
      productBadge: "TURBO UPI 2.0",
      productSub: "POWERED BY RAZORPAY CHECKOUT",
      pills: [
        { label: "3DS Friction", value: "1-Click UPI Intent" },
        { label: "Bank Outage", value: "Jitter Resequence" },
        { label: "Mandate Fail", value: "Hinglish Voice IVR" }
      ]
    }
  ];

  const current = SLIDES[heroSlide % SLIDES.length];

  return (
    <div className="space-y-0 font-sans">

      {/* ═══════════════════════════════════════════════════════════════
          HERO SECTION — Matches razorpay.com Homepage Screenshot 1
          White/light gradient bg, left-aligned headline, right visual card
          ═══════════════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-white via-[#F0F7FF] to-[#E2EFFE] border border-slate-200/60 shadow-sm">
        
        {/* Subtle atmospheric glow (official Razorpay has a slight blue ambient) */}
        <div className="pointer-events-none absolute -top-40 left-1/3 w-[600px] h-[400px] bg-blue-200/30 rounded-full blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 right-0 w-[500px] h-[400px] bg-cyan-100/20 rounded-full blur-3xl" />

        <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-10 items-center px-8 sm:px-12 lg:px-16 py-12 lg:py-16">
          
          {/* ── LEFT: Headline, Subline, CTAs, Arrows ── */}
          <div className="lg:col-span-7 space-y-7">
            <h1 className="text-[42px] sm:text-[50px] lg:text-[56px] font-extrabold leading-[1.08] tracking-tight">
              <span className="block text-[#2563EB]">{current.titleBlue}</span>
              <span className="block text-[#1B1F36] mt-1">{current.titleDark}</span>
            </h1>

            <p className="text-[13px] sm:text-sm font-medium text-[#64748B] tracking-wide">
              {current.subline}
            </p>

            {/* CTAs — Blue filled "Sign Up Now" + text "Know More" */}
            <div className="flex items-center gap-5 pt-1">
              <button
                onClick={() => onNavigateTab('overview')}
                className="px-6 py-3 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-bold shadow-lg shadow-blue-500/25 transition-all hover:shadow-blue-500/35 active:scale-[0.98] cursor-pointer"
              >
                Sign Up Now
              </button>
              <button
                onClick={() => onNavigateTab('docs')}
                className="text-[#2563EB] hover:text-[#1D4ED8] text-sm font-bold hover:underline cursor-pointer"
              >
                Know More
              </button>
            </div>

            {/* Carousel arrows */}
            <div className="flex items-center gap-2.5 pt-3">
              <button 
                onClick={() => setHeroSlide(prev => (prev === 0 ? SLIDES.length - 1 : prev - 1))}
                className="w-9 h-9 rounded-full border border-slate-300 bg-white hover:bg-slate-50 text-[#475569] flex items-center justify-center shadow-xs transition-colors cursor-pointer"
              >
                <ChevronLeft size={16} strokeWidth={2} />
              </button>
              <button 
                onClick={() => setHeroSlide(prev => prev + 1)}
                className="w-9 h-9 rounded-full border border-slate-300 bg-white hover:bg-slate-50 text-[#475569] flex items-center justify-center shadow-xs transition-colors cursor-pointer"
              >
                <ChevronRight size={16} strokeWidth={2} />
              </button>
            </div>
          </div>

          {/* ── RIGHT: Visual card with founder avatar + floating badges ── */}
          <div className="lg:col-span-5 flex items-center justify-center">
            <div className="relative w-full max-w-[380px] aspect-[4/5] rounded-3xl bg-gradient-to-b from-[#1E3A5F] via-[#1E3A8A] to-[#3B82F6] overflow-visible shadow-2xl flex flex-col justify-end p-6">
              
              {/* Product badge (top-right corner like Razorpay COMET card) */}
              <div className="absolute top-5 right-5 p-3 rounded-2xl bg-white/10 backdrop-blur-lg border border-white/20 text-white text-right max-w-[180px]">
                <div className="text-[11px] font-black tracking-wider flex items-center justify-end gap-1 uppercase">
                  <span>{current.productBadge}</span>
                  <Sparkles size={10} className="text-cyan-300" />
                </div>
                <div className="text-[8px] font-mono text-cyan-200/80 tracking-wider mt-0.5 uppercase">
                  {current.productSub}
                </div>
              </div>

              {/* Central avatar circle + branding text */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="flex flex-col items-center gap-2">
                  <div className="w-20 h-20 rounded-full bg-gradient-to-br from-cyan-400 to-blue-500 flex items-center justify-center text-3xl font-black text-[#0C2340] shadow-xl shadow-cyan-500/40">
                    R
                  </div>
                  <div className="text-white text-sm font-bold tracking-tight">Razorpay Recovery</div>
                  <div className="text-cyan-300/80 text-[10px] font-mono tracking-wider">Foundation Engine</div>
                </div>
              </div>

              {/* Floating status badges (right side, stacked — matching Razorpay screenshot) */}
              <div className="absolute right-3 bottom-24 space-y-2 z-20">
                {current.pills.map((pill, idx) => (
                  <div 
                    key={idx}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/90 backdrop-blur-md shadow-md text-[11px] font-medium text-[#1B1F36] whitespace-nowrap"
                  >
                    <span className="text-[#64748B]">{pill.label}</span>
                    {pill.value && (
                      <>
                        <span className="text-[#64748B]">:</span>
                        <span className="font-bold text-[#2563EB] font-mono text-[10px]">{pill.value}</span>
                      </>
                    )}
                  </div>
                ))}
              </div>

              {/* Founder name pill (bottom-left) */}
              <div className="relative z-20 self-start mt-auto">
                <div className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-[#0C2340]/80 backdrop-blur-lg border border-white/15 text-white text-xs font-bold shadow-lg">
                  <span>{current.founderName}</span>
                  <span className="text-cyan-300 font-normal text-[11px]">{current.founderRole}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── BOTTOM: Recommendation pill bar (matches Razorpay screenshot 1 exactly) ── */}
        <div className="relative z-10 px-8 sm:px-12 lg:px-16 pb-6 pt-2">
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
                className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white hover:bg-blue-50 border border-slate-200 text-[#2563EB] shrink-0 transition-colors cursor-pointer shadow-xs"
              >
                <PillIcon size={13} />
                <span>{label}</span>
              </button>
            ))}

            <button 
              onClick={() => onNavigateTab('docs')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white hover:bg-slate-50 border border-slate-200 text-[#64748B] shrink-0 transition-colors cursor-pointer shadow-xs"
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
      <section className="mt-16 space-y-10">
        <h2 className="text-[32px] sm:text-[38px] lg:text-[42px] font-extrabold text-[#1B1F36] tracking-tight leading-tight">
          We have innovated at every instance, creating a disruption.
        </h2>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
          
          {/* Card 1: MoneySaver / AI Diagnostic (Large — col-span-7) */}
          <div className="lg:col-span-7 rounded-2xl bg-white border border-slate-200/80 p-8 sm:p-10 shadow-[0_2px_20px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_30px_rgba(0,0,0,0.08)] transition-shadow duration-300 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-[#64748B] mb-7">
                <span className="tracking-wide">MoneySaver Export Account</span>
                <Globe size={22} className="text-[#1B1F36]" />
              </div>

              <h3 className="text-[26px] sm:text-[30px] lg:text-[34px] font-extrabold text-[#1B1F36] leading-[1.2] tracking-tight">
                <span className="text-[#2563EB]">Open a virtual account in 200+ countries, </span>
                save up to 50% on international bank transfer charges. Receive ACH/SWIFT/SEPA/BACS payments
              </h3>

              <p className="mt-8 text-sm text-[#64748B] font-medium leading-relaxed">
                Receive international wire transfers with ease with a smart account
              </p>
            </div>

            <div className="flex items-center gap-5 pt-8">
              <button 
                onClick={() => onNavigateTab('overview')}
                className="flex items-center gap-2 px-5 py-3 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-bold shadow-md shadow-blue-500/20 transition-all cursor-pointer"
              >
                <span>Sign Up</span>
                <ArrowRight size={14} strokeWidth={2.5} />
              </button>
              <button 
                onClick={() => onNavigateTab('docs')}
                className="text-[#1B1F36] hover:text-[#2563EB] text-sm font-bold hover:underline cursor-pointer"
              >
                Know More
              </button>
            </div>
          </div>

          {/* Card 2: Turbo UPI / Recovery (Smaller — col-span-5) */}
          <div className="lg:col-span-5 relative rounded-2xl bg-white border border-slate-200/80 p-8 sm:p-10 shadow-[0_2px_20px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_30px_rgba(0,0,0,0.08)] transition-shadow duration-300 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-[#64748B] mb-7">
                <span className="tracking-wide">Turbo UPI</span>
                <Zap size={22} className="text-[#1B1F36]" />
              </div>

              <h3 className="text-[22px] sm:text-[26px] font-extrabold text-[#1B1F36] leading-[1.2] tracking-tight">
                <span className="text-[#2563EB]">Experience a 5X faster checkout, </span>
                achieve a 10% success rate boost, all without any redirections to UPI apps.
              </h3>

              <p className="mt-8 text-xs sm:text-sm text-[#64748B] font-medium leading-relaxed">
                Get India's fastest one-step UPI payment solution for businesses
              </p>
            </div>

            <div className="flex items-center gap-5 pt-8">
              <button 
                onClick={() => onNavigateTab('overview')}
                className="flex items-center gap-2 px-5 py-3 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-bold shadow-md shadow-blue-500/20 transition-all cursor-pointer"
              >
                <span>Sign Up</span>
                <ArrowRight size={14} strokeWidth={2.5} />
              </button>
              <button 
                onClick={() => onNavigateTab('docs')}
                className="text-[#1B1F36] hover:text-[#2563EB] text-sm font-bold hover:underline cursor-pointer"
              >
                Know More
              </button>
            </div>

            {/* Floating carousel circle arrow (right edge, matching Razorpay) */}
            <div className="hidden lg:flex absolute -right-4 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-[#2563EB] text-white items-center justify-center shadow-lg cursor-pointer hover:scale-110 transition-transform z-10">
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
