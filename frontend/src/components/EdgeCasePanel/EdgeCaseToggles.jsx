import { UserX, Unplug, Siren } from 'lucide-react';

const BUTTONS = [
  {
    key: 'opt-out',
    label: 'Opt-Out',
    icon: UserX,
    title: 'Trigger customer opt-out on a random INTERVENING record',
    hoverClass: 'drill-btn-amber',
  },
  {
    key: 'bank-outage',
    label: 'Bank Outage',
    icon: Unplug,
    title: 'Simulate bank outage for transient records',
    hoverClass: 'drill-btn-blue',
  },
  {
    key: 'fraud',
    label: 'Fraud Alert',
    icon: Siren,
    title: 'Trigger fraud flag on a random record',
    hoverClass: 'drill-btn-rose',
  },
];

export default function EdgeCaseToggles({ onOptOut, onBankOutage, onFraudAlert }) {
  const handlers = { 'opt-out': onOptOut, 'bank-outage': onBankOutage, fraud: onFraudAlert };

  return (
    <div className="flex items-center gap-2">
      <span className="mr-1 hidden text-[10px] font-bold uppercase tracking-widest text-ink-faint lg:block">
        Drills
      </span>
      {BUTTONS.map(({ key, label, icon: Icon, title, hoverClass }) => (
        <button
          key={key}
          className={`drill-btn inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] font-medium text-slate-400 backdrop-blur transition-all duration-300 ease-out hover:-translate-y-0.5 ${hoverClass}`}
          onClick={handlers[key]}
          title={title}
        >
          <Icon size={13} strokeWidth={2} />
          {label}
        </button>
      ))}
    </div>
  );
}