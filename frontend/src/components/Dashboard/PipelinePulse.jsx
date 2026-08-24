import {
  Inbox,
  BrainCircuit,
  Zap,
  CircleCheck,
  OctagonX,
} from 'lucide-react';
import { formatINR } from '../../utils/formatters';

const STATES = [
  { key: 'INGESTED', label: 'Ingested', icon: Inbox, tint: 'text-slate-300', bar: 'bg-slate-400/70' },
  { key: 'DIAGNOSED', label: 'Diagnosed', icon: BrainCircuit, tint: 'text-blue-300', bar: 'bg-blue-400/80' },
  { key: 'INTERVENING', label: 'Intervening', icon: Zap, tint: 'text-amber-300', bar: 'bg-amber-400/80' },
  { key: 'RECOVERED', label: 'Recovered', icon: CircleCheck, tint: 'text-emerald-300', bar: 'bg-emerald-400/90' },
  { key: 'FAILED_STOPPED', label: 'Stopped', icon: OctagonX, tint: 'text-rose-300', bar: 'bg-rose-400/70' },
];

/**
 * Compact "Pipeline Pulse" widget for the hero band — a live mini-map of the
 * five-state pipeline with floating metric pills.
 */
export default function PipelinePulse({ records = [], metrics = {} }) {
  const counts = Object.fromEntries(STATES.map((s) => [s.key, 0]));
  records.forEach((r) => {
    if (counts[r.recovery_state] !== undefined) counts[r.recovery_state] += 1;
  });
  const max = Math.max(1, ...Object.values(counts));
  const recoveredGmv = (metrics.recovered_gmv || 0) / 100;
  const netRoi = metrics.net_roi || 0;

  return (
    <div className="relative hidden w-[300px] shrink-0 md:block">
      {/* Floating metric pills */}
      <div className="absolute -top-3 right-3 z-20 flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-canvas-800 px-3 py-1 shadow-lg shadow-emerald-500/10">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        <span className="font-mono text-[11px] font-semibold text-emerald-300">
          ₹{recoveredGmv.toLocaleString('en-IN')} recovered
        </span>
      </div>
      <div className="absolute -bottom-2.5 left-4 z-20 flex items-center gap-1.5 rounded-full border border-cyan-400/25 bg-canvas-800 px-3 py-1 shadow-lg shadow-cyan-500/10">
        <span className="h-1.5 w-1.5 rounded-full bg-cyan-glow" />
        <span className="font-mono text-[11px] font-semibold text-cyan-200">
          Net ROI {formatINR(netRoi)}
        </span>
      </div>

      {/* Widget card */}
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-md transition-all duration-300 ease-out hover:-translate-y-0.5 hover:border-blue-500/30">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-widest text-ink-faint">
            Pipeline Pulse
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-ink-muted">
            {records.length} records
          </span>
        </div>

        <div className="space-y-2">
          {STATES.map(({ key, label, icon: Icon, tint, bar }) => (
            <div key={key} className="flex items-center gap-2.5">
              <Icon size={13} strokeWidth={2} className={`${tint} shrink-0`} />
              <span className="w-[74px] shrink-0 text-[11px] font-medium text-ink-body">{label}</span>
              <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className={`h-full rounded-full ${bar} transition-all duration-700 ease-out`}
                  style={{ width: `${(counts[key] / max) * 100}%` }}
                />
              </div>
              <span className="w-6 shrink-0 text-right font-mono text-[11px] font-semibold text-ink-heading">
                {counts[key]}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}