import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Radio, Activity } from 'lucide-react';
import { RECOVERY_STATE_LABELS } from '../../utils/formatters';

const MAX_EVENTS = 6;

const TO_TEXT_COLOR = {
  INGESTED: 'text-[var(--rzp-ink-muted)]',
  DIAGNOSED: 'text-[var(--rzp-blue-600)]',
  INTERVENING: 'text-amber-600',
  RECOVERED: 'text-emerald-600 font-bold',
  FAILED_STOPPED: 'text-rose-600',
};

export default function ActivityTicker({ stateChange, isConnected }) {
  const [events, setEvents] = useState([]);
  const lastSeqRef = useRef(0);

  useEffect(() => {
    if (!stateChange || stateChange._seq === lastSeqRef.current) return;
    lastSeqRef.current = stateChange._seq;

    setEvents((prev) => [
      {
        id: stateChange._seq || Date.now(),
        payment_id: stateChange.payment_id,
        from: stateChange.from,
        to: stateChange.to,
        actor: stateChange.details?.actor,
        amount: stateChange.details?.amount,
      },
      ...prev.slice(0, MAX_EVENTS - 1),
    ]);
  }, [stateChange]);

  return (
    <div className="flex h-11 shrink-0 items-center gap-3 overflow-hidden rounded-2xl border border-slate-200 bg-white px-4 shadow-sm">
      <span className="flex shrink-0 items-center gap-2 text-[10px] font-bold font-mono uppercase tracking-wider text-[var(--rzp-ink)]">
        <span className="relative flex h-2 w-2">
          {isConnected && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--rzp-blue-600)] opacity-75" />
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${isConnected ? 'bg-[var(--rzp-blue-600)]' : 'bg-slate-300'}`} />
        </span>
        Live Activity Stream
      </span>

      <span className="h-4 w-px shrink-0 bg-slate-200" />

      {events.length === 0 ? (
        <span className="truncate text-xs font-mono text-[#94A3B8]">
          Waiting for state transitions — run a recovery batch to populate the stream
        </span>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto custom-scrollbar py-1">
          {events.map((ev, i) => (
            <span
              key={ev.id}
              className={`flex shrink-0 items-center gap-2 rounded-xl border px-3 py-1 text-xs font-mono transition-all duration-300 ${
                i === 0
                  ? 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)] shadow-xs'
                  : 'border-slate-100 bg-slate-50 text-[#94A3B8] opacity-60'
              }`}
            >
              <span className="text-[#94A3B8]">{RECOVERY_STATE_LABELS[ev.from] || ev.from}</span>
              <ArrowRight size={10} strokeWidth={2.5} className="text-[var(--rzp-blue-600)]" />
              <span className={TO_TEXT_COLOR[ev.to] || 'text-[var(--rzp-ink)]'}>
                {RECOVERY_STATE_LABELS[ev.to] || ev.to}
              </span>
              {typeof ev.amount === 'number' && (
                <span className="text-[var(--rzp-ink)] font-bold pl-1 border-l border-slate-200">
                  ₹{(ev.amount / 100).toLocaleString('en-IN')}
                </span>
              )}
              {ev.actor && (
                <span className="text-[10px] text-[#94A3B8]">
                  via {ev.actor}
                </span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}