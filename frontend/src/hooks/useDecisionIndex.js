/**
 * RecoverOS — Decision index
 *
 * The dashboard's records[] carries no reason code, attempt count or spend:
 * that detail lives in the ledger, one payment at a time, behind
 * GET /api/audit/{payment_id}. This hook fetches those trails through a small
 * concurrency pool and derives a decision per record, so the queue can show
 * WHY a payment is where it is rather than only WHERE it is.
 *
 * Results stream in as they arrive rather than landing in one block, so the
 * queue is usable while the tail is still loading. Trails are cached by
 * payment id and only re-fetched when the ledger head moves, because an
 * append-only ledger cannot change an entry that has already been read.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useEffect, useRef, useState } from 'react';

import api from '../utils/api';
import { deriveDecision } from '../utils/decisions';

const DEFAULT_CONCURRENCY = 6;

export function useDecisionIndex(records, refreshKey, options = {}) {
  const { concurrency = DEFAULT_CONCURRENCY, enabled = true } = options;

  const [decisions, setDecisions] = useState({});
  const [loaded, setLoaded] = useState(0);

  // Cache survives re-renders and filter changes; only a ledger head move
  // clears it. Keeping it in a ref rather than state avoids a render per
  // cache write.
  const cacheRef = useRef(new Map());
  const lastKeyRef = useRef(null);

  const ids = (records || []).map((r) => r.payment_id).filter(Boolean);
  const idsKey = ids.join(',');

  useEffect(() => {
    // Disabled means a batch is rewriting these records. Whatever is cached
    // describes the run that just ended, so it is dropped rather than shown
    // against records currently being re-processed — a stale "Policy blocked:
    // consent withdrawn" beside a record being freshly diagnosed is the kind
    // of wrong that is worse than blank.
    if (!enabled) {
      if (cacheRef.current.size > 0) {
        cacheRef.current = new Map();
        lastKeyRef.current = null;
        setDecisions({});
        setLoaded(0);
      }
      return undefined;
    }

    if (ids.length === 0) return undefined;

    // A new ledger head means new entries; anything cached is now a prefix of
    // the truth rather than the truth.
    if (lastKeyRef.current !== refreshKey) {
      cacheRef.current = new Map();
      lastKeyRef.current = refreshKey;
    }

    let cancelled = false;
    const cache = cacheRef.current;

    const pending = ids.filter((id) => !cache.has(id));

    // Seed from cache immediately so a filter change does not blank the queue.
    if (cache.size > 0) {
      setDecisions(Object.fromEntries(cache));
    }
    setLoaded(cache.size);

    if (pending.length === 0) return undefined;

    let cursor = 0;
    const buffer = new Map(cache);
    let sinceFlush = 0;

    const flush = () => {
      if (cancelled) return;
      setDecisions(Object.fromEntries(buffer));
      setLoaded(buffer.size);
      sinceFlush = 0;
    };

    async function worker() {
      while (!cancelled) {
        const index = cursor;
        cursor += 1;
        if (index >= pending.length) return;

        const id = pending[index];
        try {
          const data = await api.getAudit(id);
          const decision = deriveDecision(data);
          if (decision) {
            cache.set(id, decision);
            buffer.set(id, decision);
          }
        } catch {
          // A single unreadable trail must not stall the index. The record
          // simply shows no decision, which is honest: we could not read it.
        }

        sinceFlush += 1;
        // Batch renders. One setState per response repainted the queue 75
        // times for no benefit the eye can catch.
        if (sinceFlush >= concurrency) flush();
      }
    }

    const workers = Array.from(
      { length: Math.min(concurrency, pending.length) },
      () => worker()
    );

    Promise.all(workers).then(() => {
      if (!cancelled) flush();
    });

    return () => {
      cancelled = true;
    };
    // idsKey stands in for the ids array so an identical list does not
    // re-trigger the pool on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, refreshKey, enabled, concurrency]);

  return {
    decisions,
    loaded,
    total: ids.length,
    isLoading: enabled && ids.length > 0 && loaded < ids.length,
  };
}

export default useDecisionIndex;
