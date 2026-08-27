/**
 * RecoverOS — Batch Simulation Hook
 * Manages batch trigger, polling, and state.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import api from '../utils/api';

const POLL_MS = 1000;
// ~30s of no forward progress. A single record takes 100-300ms plus any model
// call, so this is far longer than a slow record and far shorter than a demo.
const STALL_POLLS = 30;

export function useBatchSimulation() {
  const [batchId, setBatchId] = useState(null);
  const [batchStatus, setBatchStatus] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
    }
  }, []);

  const startBatch = useCallback(async () => {
    try {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setError(null);
      setIsRunning(true);
      const result = await api.runBatch();
      setBatchId(result.batch_id);
      setBatchStatus({ status: 'STARTED', ...result });

      // Start polling for status.
      //
      // COMPLETED used to be the only way out of the running state, so a batch
      // that stalled left isRunning true forever and the Run button disabled
      // for the rest of the session — unrecoverable without a page reload,
      // which is the worst thing that can happen mid-demo. Progress is now
      // watched too: if processed_records stops advancing for long enough, the
      // poll gives up and hands the button back. It does NOT claim the batch
      // succeeded; batchStatus keeps whatever the server last reported.
      let lastProcessed = -1;
      let stalledPolls = 0;

      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getBatchStatus(result.batch_id);
          setBatchStatus(status);

          if (status.status === 'COMPLETED') {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setIsRunning(false);
            return;
          }

          const processed = Number(status.processed_records ?? 0);
          if (processed > lastProcessed) {
            lastProcessed = processed;
            stalledPolls = 0;
          } else if (++stalledPolls >= STALL_POLLS) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setIsRunning(false);
            setError(
              `Batch stopped advancing at ${processed}/${status.total_records ?? '?'}. `
              + 'The run may still be in progress on the server.'
            );
          }
        } catch (err) {
          console.warn('Poll error:', err);
        }
      }, POLL_MS);

      return result;
    } catch (err) {
      setError(err.message);
      setIsRunning(false);
      throw err;
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  return {
    batchId,
    batchStatus,
    isRunning,
    error,
    startBatch,
    stopPolling,
  };
}

export default useBatchSimulation;
