/**
 * RecoverOS — Formatters
 * Currency, date, percentage, and display formatting utilities.
 */

export function formatCurrency(paise, showPaise = false) {
  const inr = paise / 100;
  if (inr >= 100000) {
    return `₹${(inr / 100000).toFixed(2)}L`;
  }
  if (inr >= 1000) {
    return `₹${(inr / 1000).toFixed(1)}K`;
  }
  return `₹${inr.toLocaleString('en-IN', { minimumFractionDigits: showPaise ? 2 : 0 })}`;
}

export function formatCurrencyFull(paise) {
  const inr = paise / 100;
  return `₹${inr.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatINR(amount) {
  return `₹${amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPercent(value) {
  return `${value.toFixed(1)}%`;
}

export function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const now = new Date();
  const then = new Date(dateStr);
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ago`;
}

export function truncateId(id) {
  if (!id) return '';
  if (id.length <= 16) return id;
  return `${id.slice(0, 8)}...${id.slice(-4)}`;
}

export const FAILURE_CLASS_COLORS = {
  TRANSIENT_TECHNICAL: { bg: '#1e3a5f', text: '#60a5fa', border: '#3b82f6' },
  AUTH_FRICTION: { bg: '#4a3728', text: '#fbbf24', border: '#f59e0b' },
  MANDATE_BALANCE: { bg: '#3b1f5e', text: '#a78bfa', border: '#8b5cf6' },
  B2B_RECEIVABLE: { bg: '#1a3a3a', text: '#2dd4bf', border: '#14b8a6' },
  HARD_DECLINE: { bg: '#4a1d1d', text: '#f87171', border: '#ef4444' },
};

export const FAILURE_CLASS_LABELS = {
  TRANSIENT_TECHNICAL: 'Transient Technical',
  AUTH_FRICTION: 'Auth / Friction',
  MANDATE_BALANCE: 'Mandate / Balance',
  B2B_RECEIVABLE: 'B2B Receivable',
  HARD_DECLINE: 'Hard Decline',
};

export const RECOVERY_STATE_LABELS = {
  INGESTED: 'Ingested',
  DIAGNOSED: 'Diagnosed',
  INTERVENING: 'Active Intervention',
  RECOVERED: 'Settled (Won)',
  FAILED_STOPPED: 'Gracefully Aborted',
};

export const CHANNEL_ICONS = {
  silent_retry: '🔄',
  whatsapp_link: '💬',
  upi_resequence: '📅',
  hinglish_voice: '📞',
  email: '📧',
};
