/**
 * RecoverOS — Engine
 *
 * Answers one question: why did RecoverOS choose this action?
 *
 * It walks the six stages a failed payment passes through and, beside each
 * one, shows what that stage did to a real record read out of the ledger. The
 * examples are discovered by shape at runtime, so this page cannot drift into
 * describing a system that no longer exists.
 *
 * What this replaced was a wall of invented telemetry — "14.2ms", "142 req/s",
 * "4 Cores", "99.98% uptime", "accuracy: 94.2%", "Zero dropped webhooks" —
 * every one of them a hard-coded string that never moved when a batch ran.
 * Numbers nobody can reproduce are worse than no numbers on a page whose whole
 * argument is that its claims are checkable. Everything below is either
 * mechanism traceable to a named source file, or a figure served by the API.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useState } from 'react';
import {
  Bot,
  Cpu,
  FlaskConical,
  Loader2,
  Play,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  Wifi,
  WifiOff,
} from 'lucide-react';

import DecisionPipeline from '../Engine/DecisionPipeline';
import useEngineExamples, { EXAMPLE_SLOTS } from '../../hooks/useEngineExamples';
import { formatCurrencyFull } from '../../utils/formatters';
import { reasonMeta } from '../../utils/decisions';

/** The thesis. Everything below it is an attempt to earn these three claims. */
function Thesis() {
  const parts = [
    { icon: Bot, label: 'AI recommends.', cls: 'text-violet-700', ring: 'border-violet-200 bg-violet-50' },
    { icon: ShieldCheck, label: 'Policy decides.', cls: 'text-[var(--rzp-blue-600)]', ring: 'border-blue-200 bg-blue-50' },
    { icon: ScrollText, label: 'Ledger proves.', cls: 'text-[var(--rzp-green-dark)]', ring: 'border-[#A6F4C5] bg-[#ECFDF3]' },
  ];

  return (
    <section className="rzp-card p-5 sm:p-6">
      <p className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--rzp-ink-faint)]">
        The engine
      </p>
      <h1 className="mt-1.5 text-2xl font-extrabold tracking-tight text-[var(--rzp-ink)] sm:text-3xl">
        Why RecoverOS chose this action
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--rzp-ink-muted)]">
        A model proposes a diagnosis. It never decides whether to spend money or contact
        anyone — a policy engine does, against gates it cannot argue with. Both the
        recommendation and the decision are written to a hash-chained ledger, so neither
        has to be taken on trust.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {parts.map(({ icon: Icon, label, cls, ring }) => (
          <span
            key={label}
            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-bold ${ring} ${cls}`}
          >
            <Icon size={15} strokeWidth={2.3} />
            {label}
          </span>
        ))}
      </div>
    </section>
  );
}

/** Real infrastructure state only — no invented latency, throughput or uptime. */
function Infrastructure({ isConnected, ledger, activity, recordCount }) {
  const cells = [
    {
      label: 'Event stream',
      value: isConnected ? 'connected' : 'disconnected',
      icon: isConnected ? Wifi : WifiOff,
      cls: isConnected ? 'text-[var(--rzp-green-dark)]' : 'text-rose-600',
      sub: 'ws://…/ws/dashboard',
    },
    {
      label: 'Ledger entries',
      value: ledger?.entries != null ? ledger.entries.toLocaleString('en-IN') : '—',
      icon: ScrollText,
      cls: 'text-[var(--rzp-ink)]',
      sub: 'append-only, all runs',
    },
    {
      label: 'Records loaded',
      value: recordCount ? String(recordCount) : '—',
      icon: Cpu,
      cls: 'text-[var(--rzp-ink)]',
      sub: 'current batch scope',
    },
    {
      label: 'Rules / model',
      value: activity ? `${activity.classification_split.rule_engine} / ${activity.classification_split.llm_agent}` : '—',
      icon: Bot,
      cls: 'text-[var(--rzp-ink)]',
      sub: 'classifications this batch',
    },
    {
      label: 'Copy rejected',
      value: activity ? String(activity.rejections) : '—',
      icon: ShieldCheck,
      cls: 'text-[var(--rzp-ink)]',
      sub: 'guard fired, template sent',
    },
  ];

  return (
    <section className="rounded-2xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
          Infrastructure
        </h2>
        <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
          live values only · nothing on this row is hard-coded
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
        {cells.map(({ label, value, icon: Icon, cls, sub }) => (
          <div key={label} className="rounded-xl border border-[var(--rzp-border)] bg-white p-3">
            <span className="flex items-center gap-1.5 font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-faint)]">
              <Icon size={10} strokeWidth={2.4} />
              {label}
            </span>
            <div className={`mt-1.5 truncate font-mono text-base font-extrabold tracking-tight ${cls}`}>
              {value}
            </div>
            <div className="mt-0.5 truncate font-mono text-[9px] text-[var(--rzp-ink-faint)]">{sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ConsoleView({ records = [], isConnected = false, onRunBatch, isRunning = false }) {
  const { examples, activity, ledger, scanned, loading, error } = useEngineExamples();
  const [chosen, setChosen] = useState(null);

  const available = EXAMPLE_SLOTS.filter((s) => examples[s.key]);

  // Derived rather than synced through an effect: the default is simply "the
  // first branch that exists" until the reader picks one, so there is nothing
  // to keep in step and no render spent doing it.
  const active = (chosen && examples[chosen] ? chosen : available[0]?.key) || null;

  const current = active ? examples[active] : null;
  const slot = EXAMPLE_SLOTS.find((s) => s.key === active);

  return (
    <div className="space-y-4">
      <Thesis />

      {/* Worked example picker */}
      <section className="rzp-card p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--rzp-ink)]">
            Worked example
          </h2>
          <span className="font-mono text-[11px] text-[var(--rzp-ink-faint)]">
            {loading
              ? `reading the ledger for real examples — ${scanned} records scanned`
              : current
              ? 'every figure below is read from this record’s ledger entries'
              : 'nothing to show yet'}
          </span>
        </div>

        {loading && available.length === 0 ? (
          <div className="flex items-center gap-2 py-6 font-mono text-xs text-[var(--rzp-ink-muted)]">
            <Loader2 size={14} strokeWidth={2.4} className="animate-spin" />
            Finding one real record for each branch of the decision process…
          </div>
        ) : available.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-6 text-center">
            <p className="text-xs font-semibold text-[var(--rzp-ink)]">
              {error ? 'Could not read the ledger' : 'No records to explain yet'}
            </p>
            <p className="mt-1 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
              {error
                ? 'The API did not answer, so this page has no examples to anchor to. This says nothing about whether records exist.'
                : 'Run a batch and this page will anchor itself to real decisions.'}
            </p>
            <button
              onClick={onRunBatch}
              disabled={isRunning}
              className="rzp-btn-primary mt-3 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isRunning ? (
                <>
                  <RefreshCw size={14} strokeWidth={2.5} className="animate-spin" />
                  Running batch
                </>
              ) : (
                <>
                  <Play size={14} strokeWidth={2.5} />
                  Run recovery batch
                </>
              )}
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {available.map((s) => {
                const isActive = s.key === active;
                return (
                  <button
                    key={s.key}
                    onClick={() => setChosen(s.key)}
                    className={`cursor-pointer rounded-xl border px-3 py-2 text-left transition-all ${
                      isActive
                        ? 'border-[var(--rzp-blue-600)] bg-[var(--rzp-blue-050)] ring-1 ring-blue-300'
                        : 'border-[var(--rzp-border)] bg-white hover:border-[var(--rzp-border-strong)]'
                    }`}
                  >
                    <span
                      className={`block text-[11px] font-bold ${
                        isActive ? 'text-[var(--rzp-blue-600)]' : 'text-[var(--rzp-ink)]'
                      }`}
                    >
                      {s.label}
                    </span>
                    <span className="mt-0.5 block font-mono text-[9px] text-[var(--rzp-ink-faint)]">
                      {s.blurb}
                    </span>
                  </button>
                );
              })}
            </div>

            {current && (
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-3 py-2.5">
                <span className="font-mono text-sm font-extrabold tracking-tight text-[var(--rzp-ink)]">
                  {formatCurrencyFull(current.record.amount)}
                </span>
                <span className="text-xs font-semibold text-[var(--rzp-ink)]">
                  {current.record.customer_name}
                </span>
                <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                  {current.record.payment_id}
                </span>
                <span className="rounded-md border border-[var(--rzp-border)] bg-white px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-[var(--rzp-ink-muted)]">
                  {reasonMeta(current.decision.reasonCode).label}
                </span>
                {current.decision.verification?.valid && (
                  <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] text-[var(--rzp-green-dark)]">
                    <ShieldCheck size={10} strokeWidth={2.4} />
                    {current.decision.verification.entries_checked} entries hash correctly
                  </span>
                )}
              </div>
            )}

            {/* An inexact slot is still a real record — say so rather than
                letting it pass as the branch it stands in for. */}
            {current && !current.exact && slot && (
              <p className="mt-2 flex items-center gap-1.5 font-mono text-[10px] text-[var(--rzp-ink-faint)]">
                <FlaskConical size={10} strokeWidth={2.4} />
                No record in this batch matched “{slot.label}” exactly; showing the closest
                real one instead.
              </p>
            )}
          </>
        )}
      </section>

      {/* The process itself */}
      {current && <DecisionPipeline record={current.record} decision={current.decision} />}

      <Infrastructure
        isConnected={isConnected}
        ledger={ledger}
        activity={activity}
        recordCount={records.length}
      />
    </div>
  );
}
