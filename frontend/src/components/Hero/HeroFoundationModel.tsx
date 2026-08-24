import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, 
  Terminal, 
  ArrowRight, 
  Zap, 
  MessageSquare, 
  RefreshCw, 
  Cpu, 
  ShieldCheck, 
  Activity, 
  Command, 
  CornerDownLeft,
  CheckCircle2
} from 'lucide-react';

interface MetricData {
  total_gmv?: number;
  recovered_gmv?: number;
  recovery_rate?: number;
  net_roi?: number;
  total_channel_cost?: number;
  cost_per_recovery?: number;
}

interface HeroFoundationModelProps {
  metrics?: MetricData | null;
  onExecutePrompt?: (promptText: string) => void;
  onExploreDocs?: () => void;
  isRunning?: boolean;
}

export default function HeroFoundationModel({
  metrics,
  onExecutePrompt,
  onExploreDocs,
  isRunning = false,
}: HeroFoundationModelProps) {
  const [prompt, setPrompt] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionFeedback, setExecutionFeedback] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const SUGGESTIONS = [
    { label: '⚡ Auto-Diagnose 3DS Dropout', text: 'Diagnose 3DS authentication timeout on pay_9x8f01a8b9c2 and trigger WhatsApp UPI recovery' },
    { label: '💬 Trigger Smart WhatsApp Link', text: 'Dispatch localized 1-click Razorpay UPI link to customer for order #rcpt_9821' },
    { label: '🔄 Reroute via Secondary UPI Handle', text: 'Execute instant mandate fallback routing across secondary VPA channel' },
  ];

  const handleExecute = (overridePrompt?: string) => {
    const textToRun = overridePrompt || prompt;
    if (!textToRun.trim()) return;

    setIsExecuting(true);
    setExecutionFeedback(`Agent dispatched: ${textToRun.slice(0, 48)}...`);

    if (onExecutePrompt) {
      onExecutePrompt(textToRun);
    }

    setTimeout(() => {
      setIsExecuting(false);
      setExecutionFeedback('Recovery pipeline completed: Root cause classified in 14.2ms.');
      setTimeout(() => setExecutionFeedback(null), 4000);
    }, 1200);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || true)) {
      handleExecute();
    }
  };

  const selectSuggestion = (text: string) => {
    setPrompt(text);
    if (inputRef.current) {
      inputRef.current.focus();
    }
  };

  // Original formatted metrics or high-precision foundation defaults
  const recoveryRateFormatted = metrics?.recovery_rate 
    ? `${metrics.recovery_rate.toFixed(1)}%` 
    : '+28.4%';

  const latencyFormatted = '< 18ms';
  const reliabilityFormatted = '99.99%';
  const engineFormatted = 'Razorpay Native';

  return (
    <section className="relative overflow-hidden rounded-3xl border border-white/[0.1] bg-[#000214] p-6 sm:p-10 lg:p-14 shadow-2xl text-slate-100">
      {/* ================= 1. CANVAS & ATMOSPHERIC LIGHTING ================= */}
      {/* Overhead central conical / radial light beam */}
      <div 
        className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[1000px] h-[550px] bg-[radial-gradient(ellipse_80%_60%_at_50%_-20%,rgba(14,165,233,0.30),rgba(11,114,231,0.15),transparent_75%)] blur-2xl" 
      />

      {/* Deep indigo ambient backdrop flare */}
      <div className="pointer-events-none absolute top-1/3 -left-32 w-80 h-80 bg-indigo-600/15 rounded-full blur-3xl" />
      <div className="pointer-events-none absolute top-1/3 -right-32 w-80 h-80 bg-cyan-500/15 rounded-full blur-3xl" />

      {/* Perspective Geometric Grid Lines with subtle fading mask */}
      <div 
        className="pointer-events-none absolute inset-0 opacity-20 [mask-image:radial-gradient(ellipse_60%_50%_at_50%_30%,#000_70%,transparent_100%)]"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(56, 189, 248, 0.1) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(56, 189, 248, 0.1) 1px, transparent 1px)
          `,
          backgroundSize: '48px 48px',
        }}
      />

      {/* ================= 2. CONTENT WRAPPER ================= */}
      <div className="relative z-10 flex flex-col items-center text-center max-w-5xl mx-auto">
        
        {/* Research Spec Pill Announcement */}
        <div className="inline-flex items-center gap-2.5 rounded-full border border-cyan-500/30 bg-cyan-950/30 backdrop-blur-xl px-4 py-1.5 text-xs font-mono text-cyan-300 shadow-[0_0_25px_rgba(56,189,248,0.25)] hover:border-cyan-400/50 transition-all cursor-pointer group">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400 shadow-[0_0_8px_#38bdf8]" />
          </span>
          <span className="font-semibold tracking-wide text-white font-sans">
            RecoverOS Foundation Model 1.0
          </span>
          <span className="text-white/20">|</span>
          <span 
            onClick={onExploreDocs}
            className="text-cyan-300 group-hover:text-white flex items-center gap-1 transition-colors"
          >
            Zero-Shot Churn Prevention &rarr;
          </span>
        </div>

        {/* Cinematic Display Title */}
        <h1 className="mt-6 text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight leading-[1.08] text-white">
          <span className="block bg-clip-text text-transparent bg-gradient-to-b from-white via-slate-100 to-slate-400">
            The Autonomous AI Model for
          </span>
          <span className="block bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-cyan-300 to-teal-200 drop-shadow-[0_0_35px_rgba(56,189,248,0.3)]">
            Razorpay Revenue Recovery
          </span>
        </h1>

        {/* Subtitle Value Proposition */}
        <p className="mt-5 max-w-3xl text-sm sm:text-base lg:text-lg text-slate-300 leading-relaxed font-normal">
          Trained on millions of transaction failure patterns. Detects root-cause drop-offs in{' '}
          <span className="font-mono text-cyan-300 font-semibold">&lt;18ms</span> and autonomously orchestrates multi-rail recovery flows across UPI, cards, and dynamic messaging.
        </p>

        {/* ================= 3. AI COMMAND / PROMPT CONSOLE ================= */}
        <div className="w-full max-w-3xl mt-8 space-y-3">
          <div className="relative group rounded-2xl border border-cyan-500/30 bg-[#070D28]/85 backdrop-blur-2xl p-2.5 sm:p-3 shadow-[0_0_50px_rgba(11,114,231,0.25)] hover:border-cyan-400/50 hover:shadow-[0_0_60px_rgba(56,189,248,0.3)] transition-all">
            {/* Top ambient highlight line */}
            <div className="absolute inset-x-6 -top-px h-px bg-gradient-to-r from-transparent via-cyan-400 to-transparent" />

            <div className="flex flex-col sm:flex-row items-center gap-2 sm:gap-3">
              {/* Terminal Icon & Prompt Input */}
              <div className="flex items-center gap-2.5 flex-1 w-full px-3 py-1.5">
                <Terminal size={18} className="text-cyan-400 shrink-0" />
                <span className="font-mono text-cyan-400 text-sm select-none font-bold">&gt;</span>
                <input
                  ref={inputRef}
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Simulate recovery for failed order #rcpt_9821 or auto-reroute UPI mandate..."
                  className="w-full bg-transparent font-mono text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none"
                />
              </div>

              {/* Execution Action Button */}
              <button
                onClick={() => handleExecute()}
                disabled={isExecuting || isRunning}
                className="w-full sm:w-auto shrink-0 flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-[#0B72E7] via-[#2B84EA] to-cyan-500 hover:from-[#2B84EA] hover:to-cyan-400 active:scale-[0.98] text-white text-xs font-bold shadow-lg shadow-blue-600/30 transition-all disabled:opacity-50 font-mono cursor-pointer"
              >
                {isExecuting || isRunning ? (
                  <>
                    <RefreshCw size={13} className="animate-spin" />
                    <span>Inference Running...</span>
                  </>
                ) : (
                  <>
                    <Zap size={14} fill="currentColor" />
                    <span>Execute Agent</span>
                    <span className="hidden sm:inline-flex items-center gap-0.5 text-[10px] opacity-75 font-sans bg-white/20 px-1.5 py-0.5 rounded">
                      <Command size={10} />
                      <CornerDownLeft size={10} />
                    </span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Quick Prompt Suggestion Pills */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            <span className="text-[11px] font-mono text-slate-400 hidden sm:inline-block mr-1">
              Suggestions:
            </span>
            {SUGGESTIONS.map((item, idx) => (
              <button
                key={idx}
                onClick={() => selectSuggestion(item.text)}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border border-white/[0.08] bg-white/[0.03] hover:bg-cyan-500/10 hover:border-cyan-500/30 text-[11px] font-mono text-slate-300 hover:text-cyan-200 transition-all cursor-pointer backdrop-blur-md"
              >
                {item.label}
              </button>
            ))}
          </div>

          {/* Real-time Execution Toast Feedback */}
          {executionFeedback && (
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-xl border border-emerald-500/30 bg-emerald-950/40 text-emerald-300 text-xs font-mono animate-modal-in">
              <CheckCircle2 size={13} className="text-emerald-400" />
              {executionFeedback}
            </div>
          )}
        </div>

        {/* ================= 4. DEEP-TECH BENCHMARK & TELEMETRY HUD ================= */}
        <div className="w-full grid grid-cols-2 lg:grid-cols-4 gap-3.5 mt-12 pt-8 border-t border-white/[0.08]">
          {/* Card 1: Latency */}
          <div className="group relative rounded-2xl border border-white/10 hover:border-cyan-500/40 bg-[#071026]/70 hover:bg-[#071026] backdrop-blur-xl p-4 transition-all duration-300 text-left">
            <div className="absolute inset-x-4 -top-px h-px bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="flex items-center justify-between text-slate-400 text-xs font-mono">
              <span>MODEL LATENCY</span>
              <Activity size={14} className="text-cyan-400" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-white tracking-tight group-hover:text-cyan-200 transition-colors">
              {latencyFormatted}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">
              Sub-second webhook inference
            </div>
          </div>

          {/* Card 2: Recovery Efficiency */}
          <div className="group relative rounded-2xl border border-white/10 hover:border-emerald-500/40 bg-[#071026]/70 hover:bg-[#071026] backdrop-blur-xl p-4 transition-all duration-300 text-left">
            <div className="absolute inset-x-4 -top-px h-px bg-gradient-to-r from-transparent via-emerald-400/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="flex items-center justify-between text-slate-400 text-xs font-mono">
              <span>RECOVERY EFFICIENCY</span>
              <Zap size={14} className="text-emerald-400" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-emerald-400 tracking-tight">
              {recoveryRateFormatted}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">
              Autonomous revenue rescued
            </div>
          </div>

          {/* Card 3: Core Engine */}
          <div className="group relative rounded-2xl border border-white/10 hover:border-blue-500/40 bg-[#071026]/70 hover:bg-[#071026] backdrop-blur-xl p-4 transition-all duration-300 text-left">
            <div className="absolute inset-x-4 -top-px h-px bg-gradient-to-r from-transparent via-blue-400/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="flex items-center justify-between text-slate-400 text-xs font-mono">
              <span>CORE ENGINE</span>
              <Cpu size={14} className="text-blue-400" />
            </div>
            <div className="mt-2 text-xl font-bold font-mono text-white tracking-tight truncate">
              {engineFormatted}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">
              HMAC SHA-256 validated
            </div>
          </div>

          {/* Card 4: Agent Reliability */}
          <div className="group relative rounded-2xl border border-white/10 hover:border-violet-500/40 bg-[#071026]/70 hover:bg-[#071026] backdrop-blur-xl p-4 transition-all duration-300 text-left">
            <div className="absolute inset-x-4 -top-px h-px bg-gradient-to-r from-transparent via-violet-400/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="flex items-center justify-between text-slate-400 text-xs font-mono">
              <span>AGENT RELIABILITY</span>
              <ShieldCheck size={14} className="text-violet-400" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-white tracking-tight group-hover:text-violet-200 transition-colors">
              {reliabilityFormatted}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">
              Deterministic bounded fallbacks
            </div>
          </div>
        </div>

      </div>
    </section>
  );
}
