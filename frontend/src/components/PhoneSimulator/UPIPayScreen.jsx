import { useState } from 'react';
import { ShieldCheck, CheckCircle2, QrCode, Lock, ArrowRight } from 'lucide-react';
import { formatCurrencyFull } from '../../utils/formatters';

export default function UPIPayScreen({ record, onSettle }) {
  const [state, setState] = useState('ready');

  if (!record) return null;

  const amount = formatCurrencyFull(record.amount);

  const handlePay = async () => {
    setState('processing');
    try {
      if (onSettle) await onSettle(record.payment_id);
      setTimeout(() => setState('success'), 800);
    } catch {
      setState('ready');
    }
  };

  if (state === 'success') {
    return (
      <div className="flex flex-col h-full items-center justify-center p-6 text-center bg-[#071026]">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-500/10 border border-emerald-500/30 mb-4 shadow-xl shadow-emerald-500/20">
          <CheckCircle2 size={36} strokeWidth={2} className="text-emerald-400" />
        </div>
        <h3 className="text-lg font-extrabold text-white">Payment Recovered!</h3>
        <p className="mt-1 text-xs text-slate-300">
          <span className="text-emerald-400 font-bold font-mono">{amount}</span> settled via Razorpay UPI Rail
        </p>
        <div className="mt-4 p-3 rounded-xl bg-white/[0.03] border border-white/[0.08] text-left w-full space-y-1 text-[10px] font-mono">
          <div className="flex justify-between text-slate-400">
            <span>Txn ID:</span>
            <span className="text-slate-200 truncate max-w-[140px]">{record.payment_id}</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Status:</span>
            <span className="text-emerald-400 font-bold">SETTLED (WON)</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Timestamp:</span>
            <span className="text-slate-200">{new Date().toLocaleTimeString()}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-4 bg-white text-slate-900 justify-between">
      {/* Razorpay Top Brand */}
      <div>
        <div className="flex items-center justify-between pb-3 border-b border-slate-200">
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-6 rounded-md bg-[#0B72E7] flex items-center justify-center text-white font-black text-xs">
              R
            </div>
            <span className="text-xs font-extrabold tracking-tight text-[#071026]">
              Razorpay <span className="text-[#0B72E7] font-semibold text-[10px]">Trusted</span>
            </span>
          </div>
          <div className="flex items-center gap-1 text-[10px] text-emerald-600 font-semibold">
            <ShieldCheck size={12} />
            Verified Secure
          </div>
        </div>

        {/* Amount Box */}
        <div className="mt-4 p-4 rounded-2xl bg-slate-50 border border-slate-200/80 text-center">
          <div className="text-[11px] font-medium text-slate-500">Payable to RecoverOS Merchant</div>
          <div className="text-2xl font-black text-slate-900 font-mono mt-1">{amount}</div>
          <div className="text-[10px] text-slate-400 mt-1 font-mono">Order ref: {record.payment_id}</div>
        </div>

        {/* UPI Apps Row */}
        <div className="mt-4">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">
            Select UPI Payment Method
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="p-2.5 rounded-xl border border-blue-500/40 bg-blue-50/50 font-semibold text-blue-700 flex flex-col items-center gap-1">
              <span className="text-[11px] font-bold">GPay</span>
              <span className="text-[8px] text-blue-600">Instant</span>
            </div>
            <div className="p-2.5 rounded-xl border border-slate-200 bg-slate-50 font-medium text-slate-700 flex flex-col items-center gap-1">
              <span className="text-[11px] font-bold">PhonePe</span>
              <span className="text-[8px] text-slate-400">UPI</span>
            </div>
            <div className="p-2.5 rounded-xl border border-slate-200 bg-slate-50 font-medium text-slate-700 flex flex-col items-center gap-1">
              <span className="text-[11px] font-bold">Paytm</span>
              <span className="text-[8px] text-slate-400">UPI</span>
            </div>
          </div>
        </div>
      </div>

      {/* Action CTA */}
      <div className="pt-4 border-t border-slate-200 space-y-2">
        <button
          onClick={handlePay}
          disabled={state === 'processing'}
          className={`w-full py-3 px-4 rounded-xl bg-[#0B72E7] hover:bg-[#0959b8] active:scale-[0.98] text-white font-bold text-xs shadow-lg shadow-blue-500/30 transition-all flex items-center justify-center gap-2 ${
            state === 'processing' ? 'cursor-not-allowed opacity-75' : ''
          }`}
        >
          {state === 'processing' ? (
            <>
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              <span>Authorizing via UPI PIN...</span>
            </>
          ) : (
            <>
              <Lock size={12} />
              <span>Authorize &amp; Pay {amount}</span>
              <ArrowRight size={12} strokeWidth={2.5} />
            </>
          )}
        </button>

        <div className="text-center text-[9px] text-slate-400">
          Sandbox Simulator — Simulated Razorpay Instant Settlement
        </div>
      </div>
    </div>
  );
}