import {
  Landmark,
  IndianRupee,
  Target,
  TrendingUp,
  Wallet,
  ReceiptText,
} from 'lucide-react';
import { formatCurrency, formatCurrencyFull, formatPercent, formatINR } from '../../utils/formatters';
import { useCountUp } from '../../hooks/useCountUp';

const TINTS = {
  blue: 'bg-blue-50 text-[#2563EB] border-blue-200',
  emerald: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  cyan: 'bg-cyan-50 text-cyan-600 border-cyan-200',
  violet: 'bg-violet-50 text-violet-600 border-violet-200',
  amber: 'bg-amber-50 text-amber-600 border-amber-200',
};

function StatCard({ icon: Icon, tint, label, rawValue, format, sub }) {
  const animated = useCountUp(rawValue || 0);

  return (
    <div className="group relative rounded-2xl border border-slate-200 bg-white hover:border-blue-300 p-4 transition-all duration-300 shadow-sm hover:shadow-md hover:-translate-y-1">
      {/* Top subtle line */}
      <div className="absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-blue-300/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[#94A3B8]">
          {label}
        </span>
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-lg border ${TINTS[tint]} transition-transform group-hover:scale-110`}
        >
          <Icon size={14} strokeWidth={2.2} />
        </span>
      </div>

      <div className="mt-3 font-mono text-2xl font-extrabold tracking-tight text-[#1B1F36] group-hover:text-[#2563EB] transition-colors">
        {format(animated)}
      </div>

      <div className="mt-1 truncate font-mono text-[11px] text-[#94A3B8]">
        {sub}
      </div>
    </div>
  );
}

export default function MetricRibbon({ metrics, totalRecords = 0 }) {
  const m = metrics || {};
  const totalGmv = m.total_gmv || m.totalGmv || 0;
  const recoveredGmv = m.recovered_gmv || m.recoveredGmv || 0;
  const recoveryRate = m.recovery_rate || m.recoveryRate || 0;
  const netRoi = m.net_roi || m.netRoi || 0;
  const channelCost = m.total_channel_cost ?? m.channel_cost ?? m.channelCost ?? 0;
  const recoveredCount = m.recovered_count || m.recoveredCount || 0;
  const costPerRecovery =
    recoveredCount > 0 ? channelCost / recoveredCount : (m.cost_per_recovery || 0);
  const countTotal = m.total_records || totalRecords || 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatCard icon={Landmark} tint="blue" label="Ingested GMV" rawValue={totalGmv} format={formatCurrency} sub={formatCurrencyFull(totalGmv)} />
      <StatCard icon={IndianRupee} tint="emerald" label="Recovered GMV" rawValue={recoveredGmv} format={formatCurrency} sub={formatCurrencyFull(recoveredGmv)} />
      <StatCard icon={Target} tint="cyan" label="Recovery Rate" rawValue={recoveryRate} format={formatPercent} sub={`${recoveredCount} of ${countTotal} records`} />
      <StatCard icon={TrendingUp} tint="violet" label="Net ROI" rawValue={netRoi} format={formatINR} sub="Recovered − Spend" />
      <StatCard icon={Wallet} tint="amber" label="Channel Cost" rawValue={channelCost} format={formatINR} sub="Multi-rail spend" />
      <StatCard icon={ReceiptText} tint="blue" label="Cost / Recovery" rawValue={costPerRecovery} format={formatINR} sub="Avg per unit" />
    </div>
  );
}