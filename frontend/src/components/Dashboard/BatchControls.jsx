import { Play, ScanSearch, Sparkles, CheckCircle2 } from 'lucide-react';
import EdgeCaseToggles from '../EdgeCasePanel/EdgeCaseToggles';

export default function BatchControls({
  onRunBatch,
  isRunning,
  progress,
  onInspect,
  onOptOut,
  onBankOutage,
  onFraudAlert,
}) {
  const processed = Number(progress?.processed ?? progress?.processed_records ?? 0);
  const total = Number(progress?.total ?? progress?.total_records ?? 50);
  const completed = progress?.status === 'COMPLETED' || (!isRunning && total > 0 && processed >= total);
  const safeTotal = total > 0 ? total : 50;
  const pct = Math.min(100, (processed / safeTotal) * 100);
  const current = progress?.current_record;

  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      {/* Primary Action Button */}
      <button
        onClick={onRunBatch}
        disabled={isRunning}
        className={`group flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-white text-sm font-bold shadow-lg transition-all duration-200 cursor-pointer ${
          isRunning
            ? 'cursor-not-allowed bg-[#2563EB]/60 shadow-blue-400/10'
            : 'bg-[#2563EB] hover:bg-[#1D4ED8] shadow-blue-500/25 hover:scale-[1.02] active:scale-[0.98]'
        }`}
      >
        {isRunning ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            <span>Simulating Recoveries ({processed}/{safeTotal})...</span>
          </>
        ) : (
          <>
            <Play size={15} fill="currentColor" />
            <span>Deploy RazorpayRecoveryEngine Free</span>
          </>
        )}
      </button>

      {/* Secondary Ghost Button */}
      <button
        onClick={onInspect}
        className="flex items-center justify-center gap-2 px-5 py-3.5 rounded-xl border border-slate-300 bg-white hover:bg-slate-50 text-[#334155] hover:text-[#1B1F36] text-sm font-semibold transition-all duration-200 hover:-translate-y-0.5 cursor-pointer shadow-xs"
      >
        <ScanSearch size={16} />
        <span>Explore Architecture</span>
      </button>

      {/* Progress Bar & Current Record Pill */}
      {isRunning && (
        <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-blue-50 border border-blue-200">
          <div className="h-2 w-32 overflow-hidden rounded-full bg-blue-100">
            <div
              className="h-full rounded-full bg-gradient-to-r from-[#2563EB] via-blue-400 to-cyan-400 transition-all duration-300 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="font-mono text-xs font-bold text-[#2563EB]">
            {pct.toFixed(0)}%
          </span>
          {current?.payment_id && (
            <span
              className="hidden sm:inline-flex items-center gap-1.5 max-w-[180px] truncate text-[11px] font-mono text-[#334155]"
              title={current.payment_id}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#2563EB] animate-ping" />
              {current.customer_name || current.payment_id}
            </span>
          )}
        </div>
      )}

      {completed && !isRunning && (
        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-700 text-xs font-mono font-semibold">
          <CheckCircle2 size={14} className="text-emerald-600" />
          Batch Simulation Ready
        </div>
      )}

      {/* Edge-case drills cluster */}
      <div className="sm:ml-auto">
        <EdgeCaseToggles
          onOptOut={onOptOut}
          onBankOutage={onBankOutage}
          onFraudAlert={onFraudAlert}
        />
      </div>
    </div>
  );
}