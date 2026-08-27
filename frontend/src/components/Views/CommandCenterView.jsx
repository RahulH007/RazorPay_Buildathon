/**
 * RecoverOS — Command Center
 *
 * The judge-facing view. Reads top to bottom as one argument: what revenue is
 * at risk, what came back, where each record sits, and — one click into any
 * of them — what the model recommended and what the policy engine decided.
 *
 * Every figure is served by the existing API. Nothing here computes a metric
 * the backend does not already produce, and nothing invents one it cannot.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import ActivityTicker from '../Dashboard/ActivityTicker';
import AiActivityStrip from '../Dashboard/AiActivityStrip';
import ModelInterpretations from '../Dashboard/ModelInterpretations';
import CommandCenterHeader from '../CommandCenter/CommandCenterHeader';
import DecisionDrawer from '../CommandCenter/DecisionDrawer';
import HeroMetrics from '../CommandCenter/HeroMetrics';
import RecoveryPipeline from '../CommandCenter/RecoveryPipeline';
import RecoveryQueue from '../CommandCenter/RecoveryQueue';
import TrustStrip from '../CommandCenter/TrustStrip';
import useDecisionIndex from '../../hooks/useDecisionIndex';
import api from '../../utils/api';
import { deriveDecision } from '../../utils/decisions';

export default function CommandCenterView({
  metrics,
  records = [],
  isConnected,
  stateChange,
  isRunning,
  progress,
  processingId,
  onRunBatch,
  onOptOut,
  onFraudAlert,
  selectedRecordId,
  onSelectRecord,
  onOpenSimulator,
}) {
  const [stageFilter, setStageFilter] = useState(null);
  const [drawerRecord, setDrawerRecord] = useState(null);
  const [drawerDecision, setDrawerDecision] = useState(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState(false);

  // The ledger is append-only, so its head is a sound cache key: while the
  // head is unchanged, no trail already read can have gained an entry.
  const ledgerKey = metrics?.ledger?.head_hash || 'empty';

  // Paused while a batch runs. Every progress frame rewrites recordMap, which
  // would restart the pool dozens of times mid-run — each restart racing the
  // simulation for the same database — and the decisions it had already read
  // describe the previous run, not the one on screen. Resumes on its own when
  // the run completes and the ledger head moves.
  const index = useDecisionIndex(records, ledgerKey, { enabled: !isRunning });

  // Verified once per ledger head and shared by the trust strip and the proof
  // bar. Both make the same claim, so both must read the same check rather
  // than each calling /api/ledger/verify and risking two different answers on
  // screen at once.
  const [chain, setChain] = useState(null);
  const [chainChecking, setChainChecking] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setChainChecking(true);
    api
      .verifyLedger()
      .then((data) => {
        if (cancelled) return;
        setChain(data);
        setChainChecking(false);
      })
      .catch(() => {
        // A failed check is not an unfinished one. Leaving `chain` null while
        // `checking` stayed true spun the trust badge forever and never
        // reached the "unreachable" state it already had a design for.
        if (cancelled) return;
        setChain(null);
        setChainChecking(false);
      });
    return () => { cancelled = true; };
  }, [ledgerKey]);

  const openRecord = useCallback(
    (record) => {
      setDrawerRecord(record);
      onSelectRecord?.(record);
    },
    [onSelectRecord]
  );

  const closeDrawer = useCallback(() => setDrawerRecord(null), []);

  // The index streams in, so `decisions` changes many times while the pool
  // drains. Reading it through a ref keeps the drawer's effect keyed on the
  // record alone — depending on the map itself re-ran this on every flush and
  // fired a fresh audit request each time for a record the pool had not
  // reached yet.
  const decisionsRef = useRef(index.decisions);
  useEffect(() => {
    decisionsRef.current = index.decisions;
  }, [index.decisions]);

  // Prefer the indexed decision; fall back to an on-demand read so the drawer
  // is never blocked on the tail of the pool.
  useEffect(() => {
    if (!drawerRecord) {
      setDrawerDecision(null);
      return undefined;
    }

    const indexed = decisionsRef.current[drawerRecord.payment_id];
    if (indexed) {
      setDrawerDecision(indexed);
      setDrawerLoading(false);
      setDrawerError(false);
      return undefined;
    }

    let cancelled = false;
    setDrawerDecision(null);
    setDrawerError(false);
    setDrawerLoading(true);
    api
      .getAudit(drawerRecord.payment_id)
      .then((data) => {
        if (cancelled) return;
        setDrawerDecision(deriveDecision(data));
        setDrawerLoading(false);
      })
      .catch(() => {
        // "No entries recorded" is a claim about the ledger. A failed read is
        // a claim about the network, and the drawer must not swap one for the
        // other in a panel whose whole job is provenance.
        if (cancelled) return;
        setDrawerError(true);
        setDrawerLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [drawerRecord]);

  const handleStageSelect = (stage) =>
    setStageFilter((current) => (current === stage ? null : stage));

  return (
    <div className="space-y-4">
      <CommandCenterHeader
        isConnected={isConnected}
        ledger={metrics?.ledger}
        onRunBatch={onRunBatch}
        isRunning={isRunning}
        progress={progress}
        onOptOut={onOptOut}
        onFraudAlert={onFraudAlert}
      />

      <TrustStrip chain={chain} checking={chainChecking} />

      <HeroMetrics
        metrics={metrics}
        chain={chain}
        chainChecking={chainChecking}
        recordCount={records.length}
        recordsGmv={records.reduce((sum, r) => sum + (r.amount || 0), 0)}
      />

      <RecoveryPipeline
        records={records}
        decisions={index.decisions}
        stageFilter={stageFilter}
        onStageSelect={handleStageSelect}
        running={isRunning}
        resolving={index.isLoading}
        resolvedCount={index.loaded}
        totalCount={index.total}
      />

      {/* The ticker is a 44px status line, so it runs full width under the
          pipeline rather than sitting alone in a column beside a 620px queue.
          It is also the only panel that moves during a run. */}
      <ActivityTicker stateChange={stateChange} isConnected={isConnected} />

      <div className="flex h-[620px] flex-col xl:h-[calc(100vh-14rem)] xl:max-h-[760px] xl:min-h-[440px]">
        <RecoveryQueue
          records={records}
          decisions={index.decisions}
          selectedId={selectedRecordId}
          processingId={processingId}
          onSelect={openRecord}
          stageFilter={stageFilter}
          onClearStage={() => setStageFilter(null)}
          index={index}
        />
      </div>

      {/* Supporting evidence.
          Model activity used to sit level with the outcomes, which put the
          most impressive-sounding panel where the business result belongs.
          It is corroboration for the decisions above, not the story, so it
          reads as a footnote: muted surround, quiet heading, bottom of the
          page. Nothing is hidden — a reviewer who wants the model's working
          still has all of it. */}
      <section className="rounded-2xl border border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-3 sm:p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--rzp-ink-faint)]">
            Supporting evidence
          </h2>
          <span className="font-mono text-[10px] text-[var(--rzp-ink-faint)]">
            what the model did · every row is a ledger entry
          </span>
        </div>

        <div className="space-y-3 opacity-90 transition-opacity hover:opacity-100">
          <AiActivityStrip refreshKey={ledgerKey} />
          <ModelInterpretations refreshKey={ledgerKey} />
        </div>
      </section>

      <DecisionDrawer
        record={drawerRecord}
        decision={drawerDecision}
        loading={drawerLoading}
        error={drawerError}
        onClose={closeDrawer}
        onOpenSimulator={onOpenSimulator}
      />
    </div>
  );
}
