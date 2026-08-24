import { Zap, BrainCircuit, Shield, Activity, TrendingUp } from 'lucide-react';

const ICONS = {
  zap: Zap,
  trending: TrendingUp,
  brain: BrainCircuit,
  shield: Shield,
  activity: Activity,
};

export default function BentoCard({ 
  icon = 'zap', 
  iconColor = 'text-[#2563EB]',
  iconBg = 'bg-blue-50 border-blue-200',
  badgeLabel = '+24.8% Reclaimed',
  badgeColor = 'bg-emerald-50 border-emerald-200 text-emerald-700',
  title = 'Autonomous Fallback',
  description = 'Dynamically reroutes failed subscription mandates through secondary payment methods and localized UPI payment links.',
  className = ''
}) {
  const Icon = ICONS[icon] || Zap;

  return (
    <div className={`group relative rounded-2xl border border-slate-200 bg-white hover:border-blue-300 p-6 transition-all duration-300 shadow-sm hover:shadow-md hover:-translate-y-1 ${className}`}>
      {/* Subtle top glow line */}
      <div className="absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-blue-300/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      
      <div className="flex items-center justify-between mb-4">
        <div className={`p-2.5 rounded-xl border ${iconBg} ${iconColor} transition-transform group-hover:scale-105 duration-200`}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        <span className={`text-[11px] font-mono font-medium px-2.5 py-0.5 rounded-full border ${badgeColor}`}>
          {badgeLabel}
        </span>
      </div>
      <h3 className="text-lg font-semibold text-[#1B1F36] mb-2 group-hover:text-[#2563EB] transition-colors">{title}</h3>
      <p className="text-sm text-[#64748B] leading-relaxed">{description}</p>
    </div>
  );
}