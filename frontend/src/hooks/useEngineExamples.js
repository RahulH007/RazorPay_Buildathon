/**
 * RecoverOS — Engine worked examples
 *
 * The Engine tab explains the decision process, and an explanation is only
 * worth reading if it is anchored to something that actually happened. This
 * finds one real record for each branch of the process — a recovery that
 * settled through a Razorpay Payment Link, a diagnosis the rules could not
 * make, a refusal on economics, a refusal on consent — by reading the same
 * ledger the Command Center reads.
 *
 * Discovery is by shape, never by hard-coded payment id: a reseeded database
 * gets different ids, and an example that silently disappears is worse than no
 * example. The scan is bounded and stops as soon as every slot is filled.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useEffect, useState } from 'react';

import api from '../utils/api';
import { deriveDecision, reasonMeta } from '../utils/decisions';

/** The four branches worth showing, in the order they should be offered. */
export const EXAMPLE_SLOTS = [
  {
    key: 'settled',
    label: 'Settled via Payment Link',
    blurb: 'the full path, end to end',
    match: (d) => Boolean(d.paymentLinkId),
    // A demo-only database creates no real link, so fall back to any recovery
    // that actually spent money rather than showing this branch as empty.
    fallback: (d, r) => d.acted && r.recovery_state === 'RECOVERED' && d.spendPaise > 0,
  },
  {
    key: 'model',
    label: 'Model fallback',
    blurb: 'the rules did not recognise the code',
    // Prefer a model diagnosis that actually reached an action: a record whose
    // run ended at policy approval shows the fallback working but not what it
    // was for. Any llm_agent record still qualifies as the fallback.
    match: (d) => d.diagnosis?.actor === 'llm_agent' && Boolean(d.action),
    fallback: (d) => d.diagnosis?.actor === 'llm_agent',
  },
  {
    key: 'economics',
    label: 'Stopped on economics',
    blurb: 'recovery would destroy value',
    match: (d) => ['CAC_CEILING', 'NEGATIVE_EXPECTED_VALUE'].includes(d.reasonCode),
    fallback: (d) => ['RETRY_CAP_REACHED', 'LADDER_EXHAUSTED'].includes(d.reasonCode),
  },
  {
    key: 'consent',
    label: 'Stopped on consent',
    blurb: 'the customer said no, or it is the wrong hour',
    match: (d) => ['CONSENT_WITHDRAWN', 'QUIET_HOURS_DEFERRED'].includes(d.reasonCode),
    fallback: (d) => reasonMeta(d.reasonCode).kind === 'held',
  },
];

// No fixed cap. The scan already stops the moment every slot has an exact
// match, so the only thing a cap changed was which examples were reachable —
// and it cut off exactly the ones worth showing. The cost-ceiling and
// negative-expected-value refusals are seeded near the end of the batch, so a
// 45-record window silently downgraded the most interesting branch of the
// whole engine to a weaker fallback.
const MAX_SCAN = Infinity;
const CONCURRENCY = 5;

export function useEngineExamples() {
  const [examples, setExamples] = useState({});
  const [activity, setActivity] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [scanned, setScanned] = useState(0);
  const [loading, setLoading] = useState(true);
  // A failed read is not an empty batch. Without this the page told a reader
  // there was nothing to explain while the infrastructure row beside it
  // reported 75 records loaded.
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(false);
      try {
        const [metrics, llm] = await Promise.all([
          api.getDashboardMetrics(),
          api.getLlmActivity().catch(() => null),
        ]);
        if (cancelled) return;

        setActivity(llm);
        setLedger(metrics.ledger || null);

        const records = metrics.records || [];
        const byId = Object.fromEntries(records.map((r) => [r.payment_id, r]));

        // Order the scan so the rarest branches surface first: payments the
        // model touched are named directly in the activity feed, and a
        // settlement can only exist on a recovered record.
        const modelFirst = [
          ...new Set(
            (llm?.interpretations || [])
              .filter((i) => i.action === 'FAILURE_DIAGNOSED_LLM')
              .map((i) => i.payment_id)
          ),
        ].filter((id) => byId[id]);

        const recovered = records
          .filter((r) => r.recovery_state === 'RECOVERED')
          .map((r) => r.payment_id);
        const rest = records.map((r) => r.payment_id);

        const order = [...new Set([...modelFirst, ...recovered, ...rest])]
          .slice(0, Number.isFinite(MAX_SCAN) ? MAX_SCAN : undefined);

        const filled = {};
        const spare = {};
        let cursor = 0;
        let done = 0;

        const complete = () => EXAMPLE_SLOTS.every((s) => filled[s.key]);

        const worker = async () => {
          while (!cancelled && !complete()) {
            const i = cursor;
            cursor += 1;
            if (i >= order.length) return;

            const id = order[i];
            try {
              const decision = deriveDecision(await api.getAudit(id));
              if (!decision || cancelled) continue;

              const record = byId[id];
              for (const slot of EXAMPLE_SLOTS) {
                if (!filled[slot.key] && slot.match(decision, record)) {
                  filled[slot.key] = { record, decision };
                } else if (
                  !spare[slot.key]
                  && slot.fallback
                  && slot.fallback(decision, record)
                ) {
                  spare[slot.key] = { record, decision };
                }
              }
            } catch {
              // One unreadable trail must not end the scan.
            }
            done += 1;
            if (!cancelled) setScanned(done);
          }
        };

        await Promise.all(
          Array.from({ length: Math.min(CONCURRENCY, order.length) }, worker)
        );
        if (cancelled) return;

        // A slot with no exact match falls back to the nearest real record of
        // the same shape. It is still a real example, never a synthesised one.
        const result = {};
        EXAMPLE_SLOTS.forEach((slot) => {
          const hit = filled[slot.key] || spare[slot.key];
          if (hit) result[slot.key] = { ...hit, exact: Boolean(filled[slot.key]) };
        });

        setExamples(result);
      } catch {
        if (!cancelled) {
          setExamples({});
          setError(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, []);

  return { examples, activity, ledger, scanned, loading, error };
}

export default useEngineExamples;
