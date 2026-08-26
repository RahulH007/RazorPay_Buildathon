import { UserX, Siren } from 'lucide-react';

// A "Bank Outage" drill used to sit here. It called a handler whose entire body
// was an alert() describing behaviour that does not exist - no record moved, no
// ledger entry was written. A drill that only claims to have run is worse than
// no drill, so it is gone until fetch_payment_downtimes is actually wired.
const BUTTONS = [
  {
    key: 'opt-out',
    label: 'Opt-Out',
    icon: UserX,
    title: 'Withdraw consent on a random INTERVENING record. Suppression then crosses every other payment from that contact.',
    hoverClass: 'drill-btn-amber',
  },
  {
    key: 'fraud',
    label: 'Fraud Quarantine',
    icon: Siren,
    title: 'Halt a record on a fraud signal, recorded with actor="system" - not as a customer opt-out',
    hoverClass: 'drill-btn-rose',
  },
];

export default function EdgeCaseToggles({ onOptOut, onFraudAlert }) {
  const handlers = { 'opt-out': onOptOut, fraud: onFraudAlert };

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