/**
 * RecoverOS — API Utility
 * Axios/fetch wrappers for backend communication.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`API Error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  // Batch
  runBatch: () => apiFetch('/api/batch/run', { method: 'POST' }),
  getBatchStatus: (batchId) => apiFetch(`/api/batch/${batchId}/status`),

  // Metrics
  getDashboardMetrics: () => apiFetch('/api/metrics/dashboard'),

  // Recovery
  getRecovery: (paymentId) => apiFetch(`/api/recovery/${paymentId}`),
  optOut: (paymentId) => apiFetch(`/api/recovery/${paymentId}/opt-out`, { method: 'POST' }),
  settle: (paymentId) => apiFetch(`/api/recovery/${paymentId}/settle`, { method: 'POST' }),
  sendDTMF: (paymentId, key) => apiFetch(`/api/recovery/${paymentId}/dtmf?key=${key}`, { method: 'POST' }),

  // Audit
  getAudit: (paymentId) => apiFetch(`/api/audit/${paymentId}`),

  // Voice
  getVoiceScript: (paymentId) => apiFetch(`/api/voice/${paymentId}`),
};

export default api;
