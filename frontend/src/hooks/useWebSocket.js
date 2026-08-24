/**
 * RecoverOS — WebSocket Hook
 * Connects to ws://localhost:8000/ws/dashboard for real-time updates.
 * Exposes the latest structured events so App can apply them incrementally:
 *   - stateChange:     a record moved columns (from → to)
 *   - batchProgress:   ingestion stream + currently processing record
 *   - liveMetrics:     cumulative batch metrics (no refetch needed)
 */

import { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/dashboard';

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const [stateChange, setStateChange] = useState(null);
  const [batchProgress, setBatchProgress] = useState(null);
  const [liveMetrics, setLiveMetrics] = useState(null);

  // Event sequence number so consumers can dedupe / trigger effects reliably
  const seqRef = useRef(0);
  const wsRef = useRef(null);
  const connectRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const unmountedRef = useRef(false);

  const stamp = (data) => ({ ...data, _seq: ++seqRef.current });

  const connect = useCallback(() => {
    if (unmountedRef.current) return;
    try {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        setIsConnected(true);
        reconnectAttemptRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLastEvent(stamp({ type: data.type }));

          switch (data.type) {
            case 'state_change':
              setStateChange(stamp(data.data));
              break;
            case 'metric_update':
              setLiveMetrics(stamp(data.data));
              break;
            case 'batch_progress':
              setBatchProgress(stamp(data.data));
              break;
            default:
              break;
          }
        } catch {
          // Malformed frame — ignore
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (unmountedRef.current) return;
        // Exponential backoff reconnect
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30000);
        reconnectAttemptRef.current++;
        reconnectTimeoutRef.current = setTimeout(() => connectRef.current?.(), delay);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      // Connection construction failed — retry via onclose path
    }
  }, []);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return {
    isConnected,
    lastEvent,
    /** Latest state_change payload: { payment_id, from, to, details, _seq } */
    stateChange,
    /** Latest batch_progress payload: { batch_id, processed, total, current_record, _seq } */
    batchProgress,
    /** Latest metric_update payload: cumulative run stats + _seq */
    liveMetrics,
  };
}

export default useWebSocket;
