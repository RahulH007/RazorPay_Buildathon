import { Inbox, BrainCircuit, Zap, CircleCheck, OctagonX, ArrowRight } from 'lucide-react';
import KanbanCard from './KanbanCard';

const COLUMNS = [
  { key: 'INGESTED', label: 'Ingested', icon: Inbox, badgeBg: 'bg-slate-50 border-slate-200 text-slate-600', barColor: 'bg-slate-400' },
  { key: 'DIAGNOSED', label: 'Diagnosed', icon: BrainCircuit, badgeBg: 'bg-blue-50 border-blue-200 text-[var(--rzp-blue-600)]', barColor: 'bg-[var(--rzp-blue-600)]' },
  { key: 'INTERVENING', label: 'Intervening', icon: Zap, badgeBg: 'bg-amber-50 border-amber-200 text-amber-600', barColor: 'bg-amber-500' },
  { key: 'RECOVERED', label: 'Recovered', icon: CircleCheck, badgeBg: 'bg-emerald-50 border-emerald-200 text-emerald-600', barColor: 'bg-emerald-500' },
  { key: 'FAILED_STOPPED', label: 'Aborted', icon: OctagonX, badgeBg: 'bg-rose-50 border-rose-200 text-rose-600', barColor: 'bg-rose-500' },
];

function KanbanColumn({ col, cards, onCardClick, processingId, selectedRecordId }) {
  const Icon = col.icon;
  return (
    <div className="flex flex-col min-w-[200px] flex-1 rounded-2xl border border-slate-200 bg-white transition-all hover:border-blue-200 overflow-hidden shadow-sm">
      {/* Column header */}
      <div className="flex items-center justify-between px-3.5 py-3 border-b border-slate-100 bg-[#F8FAFC]">
        <div className="flex items-center gap-2">
          <div className={`p-1.5 rounded-lg border ${col.badgeBg}`}>
            <Icon size={13} strokeWidth={2.2} />
          </div>
          <span className="text-xs font-bold uppercase tracking-wider text-[var(--rzp-ink)]">
            {col.label}
          </span>
        </div>
        <span
          className={`rounded-full border px-2 py-0.5 font-mono text-[10px] font-bold ${
            cards.length > 0
              ? 'border-blue-200 bg-blue-50 text-[var(--rzp-blue-600)]'
              : 'border-slate-200 bg-slate-50 text-[#94A3B8]'
          }`}
        >
          {cards.length}
        </span>
      </div>

      {/* Cards Scrollable Container */}
      <div className="flex-1 overflow-y-auto p-2.5 space-y-2 max-h-[380px] min-h-[160px] custom-scrollbar">
        {cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-28 rounded-xl border border-dashed border-slate-200 text-center p-3">
            <span className="text-[11px] font-mono text-[#94A3B8] italic">No records</span>
          </div>
        ) : (
          cards.map((record) => (
            <KanbanCard
              key={record.payment_id}
              record={record}
              isProcessing={record.payment_id === processingId}
              isSelected={record.payment_id === selectedRecordId}
              onClick={() => onCardClick && onCardClick(record)}
            />
          ))
        )}
      </div>
    </div>
  );
}

export default function KanbanBoard({ records = [], onCardClick, processingId, selectedRecordId }) {
  const grouped = {
    INGESTED: [],
    DIAGNOSED: [],
    INTERVENING: [],
    RECOVERED: [],
    FAILED_STOPPED: [],
  };

  (records || []).forEach((record) => {
    const state = record.recovery_state || 'INGESTED';
    if (grouped[state]) {
      grouped[state].push(record);
    }
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--rzp-ink)] flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--rzp-blue-600)] animate-pulse" />
            Autonomous Recovery Pipeline
          </h2>
          <span className="text-xs font-mono text-[var(--rzp-ink-muted)]">
            ({records.length} Total Records)
          </span>
        </div>
        <div className="text-[11px] font-mono text-[#94A3B8] hidden sm:block">
          Click any card to inspect audit trail &amp; preview on phone simulator
        </div>
      </div>

      {/* 5 Column Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.key}
            col={col}
            cards={grouped[col.key]}
            onCardClick={onCardClick}
            processingId={processingId}
            selectedRecordId={selectedRecordId}
          />
        ))}
      </div>
    </div>
  );
}