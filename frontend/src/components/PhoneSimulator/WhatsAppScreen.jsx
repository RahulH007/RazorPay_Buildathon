import { formatCurrencyFull } from '../../utils/formatters';
import { ShieldCheck, ArrowRight, Lock } from 'lucide-react';

export default function WhatsAppScreen({ record, onPayClick }) {
  if (!record) return null;

  const amount = formatCurrencyFull(record.amount);
  const time = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="flex flex-col h-full bg-[#0B141A] text-slate-100 p-3 overflow-y-auto">
      {/* WhatsApp Header */}
      <div className="flex items-center gap-2.5 pb-3 border-b border-white/[0.08] mb-3">
        <div className="relative">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-cyan-500 text-white font-bold text-xs shadow-md">
            R
          </div>
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-emerald-500 border border-[#0B141A]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <span className="text-xs font-semibold text-white truncate">RazorpayRecoveryEngine</span>
            <ShieldCheck size={13} className="text-emerald-400 shrink-0" />
          </div>
          <div className="text-[10px] text-emerald-400 flex items-center gap-1 font-sans">
            <span>Verified Official Merchant</span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-2.5 text-xs">
        {/* Timestamp Header */}
        <div className="text-center">
          <span className="px-2.5 py-0.5 rounded-md bg-[#182229] text-[9px] font-mono text-slate-400">
            TODAY
          </span>
        </div>

        {/* Bubble 1: Greeting */}
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-[#202C33] px-3.5 py-2.5 border border-white/[0.04] shadow-sm">
            <div className="text-slate-100 leading-snug">
              Hi <strong className="text-white">{record.customer_name}</strong> 👋
            </div>
            <div className="text-[9px] text-slate-400 text-right mt-1 font-mono">{time}</div>
          </div>
        </div>

        {/* Bubble 2: Diagnosis reason */}
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-[#202C33] px-3.5 py-2.5 border border-white/[0.04] shadow-sm">
            <div className="text-slate-100 leading-relaxed">
              Your recent payment of <span className="font-bold text-cyan-300 font-mono">{amount}</span> could not be completed due to a temporary bank throttle.
            </div>
            <div className="mt-1.5 p-2 rounded-lg bg-[#111B21] border border-white/[0.04] text-[10px] text-slate-300 font-mono">
              Reason: {record.error_description || record.error_reason || 'Bank gateway timeout'}
            </div>
            <div className="text-[9px] text-slate-400 text-right mt-1 font-mono">{time}</div>
          </div>
        </div>

        {/* Bubble 3: 1-Click Action */}
        <div className="flex justify-start">
          <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-[#202C33] px-3.5 py-3 border border-white/[0.04] shadow-md">
            <div className="text-slate-100 leading-relaxed mb-2.5">
              We&apos;ve generated a secure 1-click Razorpay UPI recovery link for you:
            </div>

            <button
              onClick={onPayClick}
              className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 hover:from-blue-500 hover:to-cyan-400 py-2.5 px-3 text-xs font-bold text-white shadow-lg shadow-blue-600/30 active:scale-[0.98] transition-all flex items-center justify-center gap-1.5"
            >
              <span>Authorize UPI Payment ({amount})</span>
              <ArrowRight size={13} strokeWidth={2.5} />
            </button>

            <div className="flex items-center justify-between text-[9px] text-slate-400 mt-2">
              <span className="flex items-center gap-1">
                <Lock size={9} />
                256-bit encrypted
              </span>
              <span className="font-mono">{time}</span>
            </div>
          </div>
        </div>

        {/* Bubble 4: Opt-out notice */}
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-xl bg-[#182229]/60 px-3 py-1.5 border border-white/[0.04]">
            <div className="text-[9px] text-slate-400 leading-tight">
              Expires in 15 mins. Reply STOP to opt out anytime.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}