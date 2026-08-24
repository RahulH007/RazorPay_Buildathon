/**
 * RecoverOS — Batch Simulation Hook
 * Manages batch trigger, polling, and state.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import api from '../utils/api';

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

      // Start polling for status
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getBatchStatus(result.batch_id);
          setBatchStatus(status);
          if (status.status === 'COMPLETED') {
            clearInterval(pollRef.current);
            setIsRunning(false);
          }
        } catch (err) {
          console.warn('Poll error:', err);
        }
      }, 1000);

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
