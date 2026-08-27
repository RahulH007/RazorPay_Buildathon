/**
 * RecoverOS — Command Center header
 *
 * Names the product, states the operating mode, and carries the one idea the
 * rest of the view exists to demonstrate: the model proposes, the policy
 * engine disposes. Every number beside it is read from the live batch.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { Activity, Bot, Loader2, PlayCircle, ScrollText, ShieldCheck, Siren, UserX } from 'lucide-react';

// The two drills that exercise a guarantee rather than a happy path. Both
// write to the ledger, which is why they belong beside the run button rather
// than in a settings panel: a reviewer should be able to provoke a refusal and
// watch it get recorded.
const DRILLS = [
  {
    key: 'opt-out',
    label: 'Opt-out',
    icon: UserX,
    cls: 'hover:border-amber-400 hover:bg-amber-50 hover:text-amber-700',
    title:
      'Withdraw consent on a random INTERVENING record. Suppression then crosses every other payment from that contact.',
  },
  {
    key: 'fraud',
    label: 'Fraud halt',
    icon: Siren,
    cls: 'hover:border-rose-400 hover:bg-rose-50 hover:text-rose-700',
    title:
      'Halt a record on a fraud signal, recorded with actor="system" — not as a customer opt-out.',
  },
];

function ModeBadge({ isConnected }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[#A6F4C5] bg-[#ECFDF3] px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--rzp-green-dark)]">
      <span className="relative flex h-1.5 w-1.5">
        {isConnected && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--rzp-green)] opacity-75" />
        )}
        <span
          className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
            isConnected ? 'bg-[var(--rzp-green)]' : 'bg-[var(--rzp-ink-faint)]'
          }`}
        />
      </span>
      {isConnected ? 'Live' : 'Offline'}
      <span className="text-[var(--rzp-green-dark)]/50">•</span>
      Razorpay Test Mode
    </span>
  );
}

export default function CommandCenterHeader({
  isConnected,
  ledger,
  onRunBatch,
  isRunning,
  progress,
  onOptOut,
  onFraudAlert,
}) {
  const drillHandlers = { 'opt-out': onOptOut, fraud: onFraudAlert };
  const entries = ledger?.entries ?? null;
  const head = ledger?.head_hash || null;

  const processed = progress?.processed ?? progress?.processed_records;
  const total = progress?.total ?? progress?.total_records;
  const showProgress = isRunning && processed != null && total;

  return (
    <section className="rzp-card overflow-hidden">
      <div className="flex flex-col gap-5 p-5 sm:p-6 lg:flex-row lg:items-center lg:justify-between">
        {/* Identity */}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight text-[var(--rzp-ink)] sm:text-[28px]">
              Recover<span className="text-[var(--rzp-blue-600)]">OS</span>
            </h1>
            <ModeBadge isConnected={isConnected} />
          </div>

          <p className="mt-1 text-sm font-semibold text-[var(--rzp-ink-muted)]">
            Autonomous Revenue Recovery
          </p>

          {/* The product thesis, stated once and prominently. Everything in
              the drawer below is evidence for this sentence. */}
          <div className="mt-3.5 inline-flex flex-wrap items-center gap-2 rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-3 py-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-bold text-violet-700">
              <Bot size={13} strokeWidth={2.2} />
              AI recommends.
            </span>
            <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[var(--rzp-blue-600)]">
              <ShieldCheck size={13} strokeWidth={2.2} />
              Policy decides.
            </span>
            <span className="hidden text-[11px] text-[var(--rzp-ink-faint)] sm:inline">
              — every approval and every refusal is written to the ledger with its reason.
            </span>
          </div>
        </div>

        {/* Chain state + run control */}
        <div className="flex shrink-0 flex-col gap-3 lg:items-end">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--rzp-border)] bg-white px-2.5 py-1.5 font-mono text-[11px] text-[var(--rzp-ink-muted)]">
              <ScrollText size={12} strokeWidth={2} className="text-[var(--rzp-blue-600)]" />
              {entries != null ? `${entries.toLocaleString('en-IN')} entries` : 'chain empty'}
            </span>
            {head && (
              <span
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--rzp-border)] bg-white px-2.5 py-1.5 font-mono text-[11px] text-[var(--rzp-ink-muted)]"
                title={`chain head: ${head}`}
              >
                <Activity size={12} strokeWidth={2} className="text-[var(--rzp-ink-faint)]" />
                {head.slice(0, 12)}…
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {DRILLS.map(({ key, label, icon: Icon, cls, title }) => (
              <button
                key={key}
                onClick={drillHandlers[key]}
                title={title}
                className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--rzp-border)] bg-white px-2.5 py-2 text-[11px] font-bold text-[var(--rzp-ink-muted)] transition-colors ${cls}`}
              >
                <Icon size={12} strokeWidth={2.2} />
                {label}
              </button>
            ))}

            {/* The demo's single most important control, sized to say so.
                A judge has sixty seconds and should never have to hunt for
                the button that makes the page move. */}
            <button
              onClick={onRunBatch}
              disabled={isRunning}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[var(--rzp-blue-600)] px-6 py-3 text-[15px] font-bold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 hover:bg-[var(--rzp-blue-700)] hover:shadow-xl hover:shadow-blue-500/30 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:translate-y-0"
            >
              {isRunning ? (
                <>
                  <Loader2 size={17} strokeWidth={2.5} className="animate-spin" />
                  <span>
                    {showProgress ? `Processing ${processed}/${total}` : 'Running batch'}
                  </span>
                </>
              ) : (
                <>
                  <PlayCircle size={17} strokeWidth={2.5} />
                  <span>Run recovery batch</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Batch progress rail — only rendered while a run is actually live. */}
      {showProgress && (
        <div className="h-1 w-full bg-[var(--rzp-surface-sunken)]">
          <div
            className="h-full bg-[var(--rzp-blue-600)] transition-[width] duration-300 ease-out"
            style={{ width: `${Math.min(100, (processed / total) * 100)}%` }}
          />
        </div>
      )}
    </section>
  );
}
