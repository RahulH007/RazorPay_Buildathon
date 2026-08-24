import { useEffect, useRef } from 'react';
import {
  MessageCircle,
  CalendarClock,
  PhoneCall,
  RefreshCcw,
  Zap,
} from 'lucide-react';
import { formatCurrency, truncateId } from '../../utils/formatters';

const BADGE = {
  TRANSIENT_TECHNICAL: { cls: 'bg-blue-50 text-[#2563EB] border-blue-200', bar: 'bg-[#2563EB]', label: 'Transient' },
  AUTH_FRICTION: { cls: 'bg-amber-50 text-amber-700 border-amber-200', bar: 'bg-amber-500', label: 'Auth Friction' },
  MANDATE_BALANCE: { cls: 'bg-violet-50 text-violet-700 border-violet-200', bar: 'bg-violet-500', label: 'Mandate' },
  B2B_RECEIVABLE: { cls: 'bg-teal-50 text-teal-700 border-teal-200', bar: 'bg-teal-500', label: 'B2B Invoice' },
  HARD_DECLINE: { cls: 'bg-rose-50 text-rose-700 border-rose-200', bar: 'bg-rose-500', label: 'Hard Decline' },
};

const CHANNEL_ICON = {
  silent_retry: RefreshCcw,
  whatsapp_link: MessageCircle,
  upi_resequence: CalendarClock,
  hinglish_voice: PhoneCall,
};

const STATE_ACCENT = {
  INGESTED: 'bg-slate-400',
  DIAGNOSED: 'bg-[#2563EB]',
  INTERVENING: 'bg-amber-500',
  RECOVERED: 'bg-emerald-500',
  FAILED_STOPPED: 'bg-rose-500',
};

export default function KanbanCard({ record, onClick, isProcessing, isSelected }) {
  const failureClass = record.failure_class || '';
  const badge = BADGE[failureClass];
  const ChannelIcon = CHANNEL_ICON[record.recovery_channel];
  const cardRef = useRef(null);
  const movedAtRef = useRef(record._movedAt);

  useEffect(() => {
    if (record._movedAt && movedAtRef.current !== record._movedAt && cardRef.current) {
      movedAtRef.current = record._movedAt;
      const el = cardRef.current;
      el.classList.remove('animate-move-flash');
      void el.offsetWidth;
      el.classList.add('animate-move-flash');
    }
  }, [record._movedAt]);

  const accentColor = STATE_ACCENT[record.recovery_state] || 'bg-slate-400';

  return (
    <div
      ref={cardRef}
      onClick={onClick}
      className={`group relative cursor-pointer overflow-hidden rounded-xl border p-3 transition-all duration-200 ease-out hover:-translate-y-0.5 select-none ${
        isSelected
          ? 'border-blue-400 bg-blue-50 shadow-md ring-1 ring-blue-300'
          : isProcessing
          ? 'border-blue-300 bg-blue-50/50 shadow-sm'
          : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/30 shadow-xs'
      }`}
    >
      {/* Accent left line */}
      <span className={`absolute inset-y-0 left-0 w-1 ${badge ? badge.bar : accentColor}`} />

      {/* Processing Pulse */}
      {isProcessing && (
        <span className="absolute right-2 top-2 h-2 w-2 animate-ping rounded-full bg-[#2563EB]" />
      )}

      {/* Top row: ID + Amount */}
      <div className="flex items-center justify-between gap-2 pl-1.5">
        <span className="truncate font-mono text-[10px] text-[#94A3B8] group-hover:text-[#64748B]">
          {truncateId(record.payment_id)}
        </span>
        <span className="shrink-0 font-mono text-xs font-bold text-[#1B1F36] tracking-tight">
          {formatCurrency(record.amount)}
        </span>
      </div>

      {/* Customer Name */}
      <div className="mt-1 truncate pl-1.5 text-xs font-medium text-[#334155]">
        {record.customer_name}
      </div>

      {/* Bottom tags */}
      <div className="mt-2.5 flex items-center justify-between gap-1.5 pl-1.5">
        {badge ? (
          <span
            className={`rounded-md border px-2 py-0.5 text-[9px] font-mono font-bold uppercase tracking-wider ${badge.cls}`}
          >
            {badge.label}
          </span>
        ) : (
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[9px] font-mono font-medium text-[#94A3B8]">
            Diagnosing...
          </span>
        )}

        {ChannelIcon && (
          <div className="p-1 rounded bg-blue-50 border border-blue-200 text-[#2563EB]" title={record.recovery_channel}>
            <ChannelIcon size={12} strokeWidth={2.2} />
          </div>
        )}
      </div>
    </div>
  );
}