import { User, Code2, Layers, Cpu, Globe, Award, Sparkles, Zap, ShieldCheck } from 'lucide-react';

export default function AboutRahulView() {
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Profile Header Bento */}
      <div className="p-8 rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-[#F4F9FF] to-[#E8F3FF] shadow-sm relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-100/30 rounded-full blur-3xl pointer-events-none" />

        <div className="flex flex-col md:flex-row items-center md:items-start gap-6 relative z-10">
          <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-[var(--rzp-blue-600)] via-[#3B82F6] to-cyan-400 p-0.5 shadow-lg shadow-blue-500/15 shrink-0">
            <div className="w-full h-full rounded-[14px] bg-white flex items-center justify-center">
              <span className="text-3xl font-extrabold text-[var(--rzp-blue-600)]">
                R
              </span>
            </div>
          </div>

          <div className="flex-1 text-center md:text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-200 bg-emerald-50 text-xs font-mono text-emerald-700 mb-2">
              <Sparkles size={12} />
              Full Stack Systems &amp; Fintech Engineer
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[var(--rzp-ink)] tracking-tight">
              Rahul — Architect of RazorpayRecoveryEngine
            </h1>
            <p className="mt-2 text-sm text-[var(--rzp-ink-muted)] leading-relaxed max-w-2xl">
              Engineered RazorpayRecoveryEngine to tackle India&apos;s ₹12,000 Cr+ failed online checkout problem by building an autonomous, low-latency revenue recovery engine adhering to Razorpay&apos;s design system and institutional banking standards.
            </p>
          </div>
        </div>
      </div>

      {/* Engineering Pillars */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow">
          <div className="p-2.5 w-fit rounded-xl bg-blue-50 border border-blue-200 text-[var(--rzp-blue-600)] mb-3">
            <Cpu size={18} />
          </div>
          <h3 className="text-sm font-bold text-[var(--rzp-ink)] mb-1">Low-Latency Async Engine</h3>
          <p className="text-xs text-[var(--rzp-ink-muted)] leading-relaxed">
            Built with FastAPI, Python asyncio event loops, and non-blocking WebSockets for &lt;18ms AI diagnosis and real-time state syncing.
          </p>
        </div>

        <div className="p-5 rounded-2xl border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow">
          <div className="p-2.5 w-fit rounded-xl bg-cyan-50 border border-cyan-200 text-cyan-600 mb-3">
            <Layers size={18} />
          </div>
          <h3 className="text-sm font-bold text-[var(--rzp-ink)] mb-1">Razorpay Blade UI/UX</h3>
          <p className="text-xs text-[var(--rzp-ink-muted)] leading-relaxed">
            Crafted with modern clean design, atmospheric lighting, interactive phone simulation, and Razorpay's official design language.
          </p>
        </div>

        <div className="p-5 rounded-2xl border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow">
          <div className="p-2.5 w-fit rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-600 mb-3">
            <ShieldCheck size={18} />
          </div>
          <h3 className="text-sm font-bold text-[var(--rzp-ink)] mb-1">Financial Audit Trails</h3>
          <p className="text-xs text-[var(--rzp-ink-muted)] leading-relaxed">
            Every recovery decision, opt-out event, channel expense, and settlement is cryptographically logged and inspectable via Audit Inspector.
          </p>
        </div>
      </div>

      {/* Tech Stack Matrix */}
      <div className="p-6 rounded-2xl border border-slate-200 bg-white shadow-sm">
        <h3 className="text-sm font-bold text-[var(--rzp-ink)] font-mono mb-4 flex items-center gap-2">
          <Code2 size={16} className="text-[var(--rzp-blue-600)]" />
          Technical Stack &amp; Technologies Used
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
          <div className="p-3 rounded-xl bg-[#F8FAFC] border border-slate-100">
            <span className="text-[#94A3B8] block text-[10px]">BACKEND</span>
            <span className="text-[var(--rzp-ink)] font-semibold">FastAPI / Python 3.11</span>
          </div>
          <div className="p-3 rounded-xl bg-[#F8FAFC] border border-slate-100">
            <span className="text-[#94A3B8] block text-[10px]">FRONTEND</span>
            <span className="text-[var(--rzp-ink)] font-semibold">React 18 / Vite / Tailwind</span>
          </div>
          <div className="p-3 rounded-xl bg-[#F8FAFC] border border-slate-100">
            <span className="text-[#94A3B8] block text-[10px]">COMMUNICATION</span>
            <span className="text-[var(--rzp-ink)] font-semibold">WebSocket / REST APIs</span>
          </div>
          <div className="p-3 rounded-xl bg-[#F8FAFC] border border-slate-100">
            <span className="text-[#94A3B8] block text-[10px]">DESIGN SYSTEM</span>
            <span className="text-[var(--rzp-ink)] font-semibold">Razorpay Blade Aesthetic</span>
          </div>
        </div>
      </div>
    </div>
  );
}
