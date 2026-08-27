/**
 * RecoverOS — Hero metrics
 *
 * Five numbers, in the order a merchant would ask for them: what is at risk,
 * what came back, how often, what it cost, and what each recovery cost.
 *
 * Scope is printed on the two money tiles rather than assumed. The dashboard
 * scopes channel spend to the batches the current records belong to, while
 * the ledger head reports every run ever performed — both are correct, and a
 * tile that does not say which one it means is the kind of number a reviewer
 * is right to distrust.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import {
  AlertTriangle,
  Check,
  CircleCheck,
  IndianRupee,
  Link2,
  ReceiptText,
  ShieldAlert,
  Target,
  Wallet,
} from 'lucide-react';

import { useCountUp } from '../../hooks/useCountUp';
import { formatCurrency, formatCurrencyFull, formatINR, formatPercent } from '../../utils/formatters';

const TINTS = {
  rose: 'bg-rose-50 text-rose-600 border-rose-200',
  emerald: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  cyan: 'bg-cyan-50 text-cyan-600 border-cyan-200',
  amber: 'bg-amber-50 text-amber-600 border-amber-200',
  blue: 'bg-blue-50 text-[var(--rzp-blue-600)] border-blue-200',
};

function MetricTile({ icon: Icon, tint, label, rawValue, format, sub, scope }) {
  const animated = useCountUp(rawValue || 0);

  return (
    <div className="group relative rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[#94A3B8]">
          {label}
        </span>
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${TINTS[tint]} transition-transform group-hover:scale-110`}
        >
          <Icon size={14} strokeWidth={2.2} />
        </span>
      </div>

      <div className="mt-3 truncate font-mono text-xl font-extrabold tracking-tight text-[var(--rzp-ink)] transition-colors group-hover:text-[var(--rzp-blue-600)] 2xl:text-2xl">
        {format(animated)}
      </div>

      <div className="mt-1 truncate font-mono text-[11px] text-[#94A3B8]">{sub}</div>

      {scope && (
        <div className="mt-1.5 inline-flex rounded border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-[var(--rzp-ink-faint)]">
          {scope}
        </div>
      )}
    </div>
  );
}

/**
 * The proof line. Five money tiles are a claim; this is the receipt for them.
 *
 * Deliberately one quiet row rather than a sixth tile: it answers "can I
 * believe the numbers above", which is a different question from "what are
 * the numbers", and giving it equal weight would push a metric off the row.
 */
function ProofBar({ ledger, chain, chainChecking, recoveredCount, totalRecords }) {
  const entries = chain?.entries_checked ?? ledger?.entries ?? null;
  const head = ledger?.head_hash;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] px-3 py-2">
      <span className="font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
        Proof
      </span>

      <span className="inline-flex items-baseline gap-1.5">
        <span
          className="font-mono text-[10px] text-[var(--rzp-ink-muted)]"
          title="The whole append-only chain, across every run — not just the records in this batch."
        >
          Ledger entries <span className="text-[var(--rzp-ink-faint)]">(all runs)</span>
        </span>
        <span className="font-mono text-xs font-bold text-[var(--rzp-ink)]">
          {entries != null ? entries.toLocaleString('en-IN') : '—'}
        </span>
      </span>

      <span className="inline-flex items-center gap-1.5">
        <span className="font-mono text-[10px] text-[var(--rzp-ink-muted)]">Chain</span>
        {chainChecking ? (
          <span className="font-mono text-xs font-bold text-[var(--rzp-ink-faint)]">checking…</span>
        ) : chain == null ? (
          <span className="font-mono text-xs font-bold text-[var(--rzp-ink-faint)]">unverified</span>
        ) : chain.valid ? (
          <span className="inline-flex items-center gap-1 font-mono text-xs font-bold text-[var(--rzp-green-dark)]">
            <Check size={11} strokeWidth={3} />
            intact
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 font-mono text-xs font-bold text-rose-600">
            <ShieldAlert size={11} strokeWidth={2.4} />
            broken at #{chain.first_broken_sequence}
          </span>
        )}
      </span>

      <span className="inline-flex items-center gap-1.5">
        <span
          className="font-mono text-[10px] text-[var(--rzp-ink-muted)]"
          title="Records in the current batch that reached RECOVERED."
        >
          Recovered <span className="text-[var(--rzp-ink-faint)]">(this batch)</span>
        </span>
        <span className="inline-flex items-center gap-1 font-mono text-xs font-bold text-emerald-700">
          <CircleCheck size={11} strokeWidth={2.4} />
          {recoveredCount} of {totalRecords}
        </span>
      </span>

      {head && (
        <span
          className="ml-auto hidden items-center gap-1 font-mono text-[10px] text-[var(--rzp-ink-faint)] lg:inline-flex"
          title={`chain head: ${head}`}
        >
          <Link2 size={10} strokeWidth={2} />
          {head.slice(0, 16)}…
        </span>
      )}
    </div>
  );
}

export default function HeroMetrics({
  metrics,
  chain,
  chainChecking,
  recordCount = 0,
  recordsGmv = 0,
}) {
  const m = metrics || {};

  // "Revenue at risk" must name the same quantity as the bar below it. The
  // websocket reports GMV accumulated *so far in the run*, so reading it here
  // made this tile say ₹2.40L while the pipeline said ₹2,75,193.50 — same
  // label, same "75 failed payments" caption, two different numbers, live in
  // front of whoever is watching the run. The book does not shrink because a
  // batch is halfway through it.
  const totalGmv = recordsGmv || m.total_gmv || 0;
  const recoveredGmv = m.recovered_gmv || 0;
  const recoveredCount = m.recovered_count || 0;

  // While a batch runs, the websocket sends cumulative stats that overlay the
  // last full fetch — but it names spend `channel_cost_paise`, where the REST
  // payload says `total_channel_cost`. Reading only the REST name left the two
  // cost tiles frozen while recovered GMV climbed beside them, which reads as
  // free recovery. Both names are real fields from the same backend; this just
  // accepts whichever arrived last.
  const channelCost =
    m.total_channel_cost ?? (m.channel_cost_paise != null ? m.channel_cost_paise / 100 : 0);
  const costPerRecovery =
    m.cost_per_recovery ?? (recoveredCount > 0 ? channelCost / recoveredCount : 0);

  // records[] is the live truth during a run; total_records only refreshes on
  // a full fetch. Preferring the former keeps this caption and the pipeline's
  // from disagreeing mid-batch.
  const totalRecords = recordCount || m.total_records || 0;

  // Mid-run the backend's rate is recovered/processed, so pairing it with a
  // denominator of 75 printed "32.8% — 20 of 75 records", which is 26.7%. The
  // rate and its own caption must divide the same two numbers.
  const isLiveRun = m.processed != null;
  const rateDenominator = isLiveRun ? m.processed : totalRecords;

  // Derived from the two numbers this tile prints, not read from the payload.
  // `metrics` is a merge of the REST snapshot and the latest websocket frame,
  // so mid-run it could hold a rate computed over all 75 records beside a
  // denominator of 52 — the tile contradicting its own caption by a point.
  // Dividing what is on screen makes that impossible. Idle, this equals the
  // backend's own recovery_rate exactly (both are recovered / total records).
  const recoveryRate =
    rateDenominator > 0 ? (recoveredCount / rateDenominator) * 100 : 0;

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricTile
          icon={AlertTriangle}
          tint="rose"
          label="Revenue at risk"
          rawValue={totalGmv}
          format={formatCurrency}
          sub={formatCurrencyFull(totalGmv)}
          scope={`${totalRecords} failed payments`}
        />
        <MetricTile
          icon={IndianRupee}
          tint="emerald"
          label="Recovered GMV"
          rawValue={recoveredGmv}
          format={formatCurrency}
          sub={formatCurrencyFull(recoveredGmv)}
          scope={`${recoveredCount} settled`}
        />
        <MetricTile
          icon={Target}
          tint="cyan"
          label="Recovery rate"
          rawValue={recoveryRate}
          format={formatPercent}
          sub={`${recoveredCount} of ${rateDenominator} ${isLiveRun ? 'processed' : 'records'}`}
        />
        <MetricTile
          icon={Wallet}
          tint="amber"
          label="Recovery cost"
          rawValue={channelCost}
          format={formatINR}
          sub="All channels, this batch"
          scope="batch-scoped"
        />
        <MetricTile
          icon={ReceiptText}
          tint="blue"
          label="Cost / recovery"
          rawValue={costPerRecovery}
          format={formatINR}
          sub={recoveredCount > 0 ? `across ${recoveredCount} recoveries` : 'no recoveries yet'}
          scope="batch-scoped"
        />
      </div>

      <ProofBar
        ledger={m.ledger}
        chain={chain}
        chainChecking={chainChecking}
        recoveredCount={recoveredCount}
        totalRecords={totalRecords}
      />
    </div>
  );
}
