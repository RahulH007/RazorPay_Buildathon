/**
 * RecoverOS — Resources
 *
 * A developer and reviewer hub: understand it, inspect it, verify it.
 *
 * Everything quoted here is real. The code panels are verbatim excerpts from
 * this repository with their true filenames, the endpoint table is the actual
 * FastAPI route surface, and the commands are the actual Makefile targets. The
 * SDK panel this replaced showed `import { RecoverOS } from 'recoveros'` for a
 * package that has never been published — a fabricated integration is the one
 * thing a developer checks first and the fastest way to lose them.
 *
 * The chain-verification badge is the only claim on this page re-checked at
 * runtime; every other mechanism is marked as source-backed and names the file
 * that backs it, exactly as the Command Center's trust strip does.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  Bot,
  Check,
  CircleCheck,
  Copy,
  FileCode2,
  FlaskConical,
  GitBranch,
  Loader2,
  Radar,
  ScrollText,
  Send,
  ShieldCheck,
  Table2,
  Terminal,
  Webhook,
} from 'lucide-react';

import api from '../../utils/api';

/* ── Real excerpts. Verbatim, with their true filenames. No secret values
      appear — only the NAME of the environment variable that holds one. ──── */
const CODE = {
  webhooks: {
    file: 'backend/app/routes/webhooks.py',
    lang: 'python',
    caption: 'Every inbound event is authenticated before it can create work.',
    body: `def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret_is_usable = bool(RAZORPAY_WEBHOOK_SECRET) and "XXXX" not in RAZORPAY_WEBHOOK_SECRET

    if not secret_is_usable:
        if DEMO_MODE:
            return True
        print("[SECURITY] Rejecting webhook: RAZORPAY_WEBHOOK_SECRET is missing "
              "or still a placeholder, and DEMO_MODE is false.")
        return False

    if not signature:
        return False

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)`,
  },
  policy: {
    file: 'backend/app/policy.py',
    lang: 'python',
    caption: 'Nine reason codes. Refusal is a recorded outcome, not a silence.',
    body: `class ReasonCode:
    """Why an action was or was not taken. Recorded verbatim in the ledger."""

    PROCEED = "PROCEED"
    HARD_DECLINE = "HARD_DECLINE"
    RETRY_CAP_REACHED = "RETRY_CAP_REACHED"
    LADDER_EXHAUSTED = "LADDER_EXHAUSTED"
    CAC_CEILING = "CAC_CEILING"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
    QUIET_HOURS_DEFERRED = "QUIET_HOURS_DEFERRED"
    NEGATIVE_EXPECTED_VALUE = "NEGATIVE_EXPECTED_VALUE"
    HOLDOUT_CONTROL = "HOLDOUT_CONTROL"
    PROMISE_TO_PAY_PENDING = "PROMISE_TO_PAY_PENDING"


def expected_value_paise(record: PaymentFailureRecord) -> int:
    """What one more successful recovery is worth, in paise."""
    rate = RECOVERY_RATES.get(record.failure_class, 0.0)
    return int(record.amount * rate * MERCHANT_MARGIN_PERCENT / 100)`,
  },
  ledger: {
    file: 'backend/app/ledger.py',
    lang: 'python',
    caption: 'Field order is part of the format. Integers only — floats are not reproducible.',
    body: `    return b"".join(
        _field(part)
        for part in (
            _int(PREIMAGE_VERSION),
            _text(prev_hash),
            _int(sequence_no),
            _text(payment_id),
            _text(batch_id),
            _int(timestamp_us),
            _text(action),
            _text(actor),
            _text(details),
            _int(cost_paise),
            # ... llm_model, token counts, latency and confidence_bp
        )
    )


def compute_entry_hash(**fields) -> str:
    """SHA-256 of the canonical preimage, as lowercase hex."""
    return hashlib.sha256(canonical(**fields)).hexdigest()`,
  },
};

/* ── The pipeline, with the file that actually implements each stage ────── */
const STAGES = [
  { n: '01', label: 'Ingest', icon: Radar,
    body: 'A Razorpay payment failure enters through the signed webhook path and is written to the ledger before anything acts on it.',
    src: 'routes/webhooks.py · event_adapter.py' },
  { n: '02', label: 'Diagnose', icon: Bot,
    body: 'A deterministic rule map runs first. Only error codes the rules do not recognise reach the model, which returns a confidence score.',
    src: 'classifier.py · llm_agent.py' },
  { n: '03', label: 'Decide', icon: ShieldCheck,
    body: 'Policy gates run cheapest-first and the first refusal wins, so the recorded reason is the most fundamental one.',
    src: 'policy.py · guardrails.py · consent.py' },
  { n: '04', label: 'Act', icon: Send,
    body: 'The escalation ladder supplies the permitted channel — silent retry, WhatsApp link, UPI re-sequence or Hinglish voice.',
    src: 'recovery_actions.py' },
  { n: '05', label: 'Settle', icon: CircleCheck,
    body: 'A Payment Link is correlated to the entry hash of the action that created it, and settles on a signed webhook exactly once.',
    src: 'settlement.py · models.py' },
  { n: '06', label: 'Prove', icon: ScrollText,
    body: 'The action and its outcome are appended to the hash-chained ledger, where anyone can recompute them.',
    src: 'ledger.py' },
];

/* ── Trust mechanisms, each labelled by how it is actually backed ───────── */
const TRUST = [
  { key: 'chain', kind: 'runtime', icon: ScrollText, label: 'Tamper-evident ledger',
    detail: 'Hash-chained audit entries', src: 'ledger.py' },
  { key: 'hmac', kind: 'source', icon: ShieldCheck, label: 'Signed webhooks',
    detail: 'HMAC-SHA256 over the exact bytes received', src: 'routes/webhooks.py' },
  { key: 'once', kind: 'source', icon: CircleCheck, label: 'Exactly-once settlement',
    detail: 'A replayed webhook settles a record once, never twice',
    src: 'tests/test_duplicate_webhook_exactly_once.py' },
  { key: 'policy', kind: 'source', icon: GitBranch, label: 'Policy guardrails',
    detail: 'Consent, quiet hours, retry caps, cost ceiling, expected value, holdout',
    src: 'policy.py · guardrails.py' },
  { key: 'mode', kind: 'scope', icon: FlaskConical, label: 'Real Razorpay Test Mode',
    detail: 'Payment Link and webhook evidence — no live money', src: null },
];

const KIND_BADGE = {
  runtime: { text: '✓ runtime verified', cls: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300' },
  source: { text: '⌗ source-backed', cls: 'border-white/12 bg-white/[0.05] text-slate-400' },
  scope: { text: '△ test mode', cls: 'border-amber-400/30 bg-amber-400/10 text-amber-300' },
};

/* ── The real FastAPI surface, prefix /api ──────────────────────────────── */
const ENDPOINTS = [
  { m: 'GET', p: '/api/metrics/dashboard', d: 'Aggregated metrics, class breakdown, lift and every record' },
  { m: 'GET', p: '/api/audit/{payment_id}', d: 'Ordered ledger entries with cost and model metadata' },
  { m: 'GET', p: '/api/audit/{payment_id}/verify', d: 'Recompute the hash of every entry for one payment' },
  { m: 'GET', p: '/api/ledger/verify', d: 'Walk the whole chain: content hashes, linkage, contiguity' },
  { m: 'GET', p: '/api/ledger/head', d: 'Current head hash, entry count and preimage version' },
  { m: 'GET', p: '/api/llm/activity', d: 'Model calls, rule/model split, rejections, cache stats' },
  { m: 'GET', p: '/api/recovery/{payment_id}', d: 'Full record with its audit trail' },
  { m: 'POST', p: '/api/batch/run', d: 'Start a batch simulation; progress streams over WebSocket' },
  { m: 'GET', p: '/api/batch/{batch_id}/status', d: 'Live batch counters and per-class breakdown' },
  { m: 'POST', p: '/api/webhooks/razorpay', d: 'Signed Razorpay webhook ingestion (HMAC-SHA256)' },
  { m: 'POST', p: '/api/recovery/{payment_id}/opt-out', d: 'Record a customer opt-out and halt recovery' },
  { m: 'POST', p: '/api/recovery/{payment_id}/quarantine', d: 'Halt on a fraud signal, recorded as a system action' },
];

/* ── The real Makefile targets ──────────────────────────────────────────── */
const COMMANDS = [
  { cmd: 'make demo', d: 'Run the seeded batch and print the demo receipt' },
  { cmd: 'make verify-ledger', d: 'Walk the chain and check every invariant' },
  { cmd: 'make tamper-demo', d: 'Edit an entry on purpose and watch verification name it' },
  { cmd: 'make test', d: 'Run the backend test suite' },
  { cmd: 'make llm-activity', d: 'Print what the model actually did, from the ledger' },
];

const RESOURCES = [
  { key: 'architecture', icon: GitBranch, title: 'Architecture & flow', body: 'The six stages a failed payment walks, and the file that implements each.' },
  { key: 'matrix', icon: Table2, title: 'Diagnostic decision matrix', body: 'Failure classes, the rail each one uses, and the assumed rate from config.py.' },
  { key: 'webhooks', icon: Webhook, title: 'Webhook specification', body: 'The payment.failed event shape RecoverOS ingests and verifies.' },
  { key: 'api', icon: Terminal, title: 'API reference', body: 'Every FastAPI route this application actually exposes.' },
  { key: 'policy', icon: ShieldCheck, title: 'Policy & guardrails', body: 'The nine reason codes and the economics behind a refusal.' },
  { key: 'verify', icon: ScrollText, title: 'Ledger verification', body: 'Commands that recompute the chain — and one that breaks it on purpose.' },
];

const MATRIX = [
  { cls: 'TRANSIENT_TECHNICAL', tone: 'text-blue-300', reason: 'Bank gateway timeout, NPCI throttle', rail: 'Silent retry', rate: '85%' },
  { cls: 'AUTH_FRICTION', tone: 'text-amber-300', reason: 'OTP timeout, 3DS abandon', rail: 'WhatsApp 1-click UPI link', rate: '40%' },
  { cls: 'MANDATE_BALANCE', tone: 'text-violet-300', reason: 'Low balance, SI throttle', rail: 'UPI re-sequence, then WhatsApp', rate: '55%' },
  { cls: 'B2B_RECEIVABLE', tone: 'text-teal-300', reason: 'Corporate limit, approval pending', rail: 'WhatsApp → Hinglish voice → human', rate: '50%' },
  { cls: 'HARD_DECLINE', tone: 'text-rose-300', reason: 'Stolen card, invalid account', rail: 'No contact. Halt and record why.', rate: '0%' },
];

const WEBHOOK_SAMPLE = `{
  "entity": "event",
  "event": "payment.failed",
  "contains": ["payment"],
  "payload": {
    "payment": {
      "entity": {
        "id": "pay_9x8f01a8b9c2",
        "amount": 499000,
        "currency": "INR",
        "status": "failed",
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "payment_failed",
        "error_description": "Payment declined by bank"
      }
    }
  }
}`;

function CopyButton({ text, id, copied, onCopy }) {
  return (
    <button
      onClick={() => onCopy(text, id)}
      className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-white/12 bg-white/[0.04] px-2 py-1 font-mono text-[10px] text-slate-400 transition-colors hover:border-white/25 hover:text-slate-200"
    >
      {copied === id ? <Check size={10} strokeWidth={3} className="text-emerald-400" /> : <Copy size={10} strokeWidth={2.2} />}
      {copied === id ? 'Copied' : 'Copy'}
    </button>
  );
}

export default function DocsView({ onNavigateTab }) {
  const [codeTab, setCodeTab] = useState('webhooks');
  const [panel, setPanel] = useState('architecture');
  const [copied, setCopied] = useState(null);
  const [chain, setChain] = useState(null);
  const [checking, setChecking] = useState(true);
  const [reverify, setReverify] = useState(false);
  const panelRef = useRef(null);

  const runVerify = () => {
    setChecking(true);
    return api.verifyLedger()
      .then((d) => { setChain(d); setChecking(false); return d; })
      .catch(() => { setChain(null); setChecking(false); });
  };

  useEffect(() => { runVerify(); }, []);

  const copy = (text, key) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(key);
    setTimeout(() => setCopied(null), 1800);
  };

  const openPanel = (key) => {
    setPanel(key);
    requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  const active = CODE[codeTab];

  return (
    <div className="bg-[#05070F] font-sans text-slate-200">
      {/* ══ HERO ═══════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden border-b border-white/[0.07]">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_0%,rgba(51,149,255,0.14),transparent_55%)]" />
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_bottom,transparent_60%,rgba(5,7,15,0.9)_100%)]" />

        <div className="rzp-container relative z-10 py-16 lg:py-20">
          <span className="inline-flex items-center rounded-md border border-[#3395FF]/35 bg-[#3395FF]/10 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-[#7FB4FF]">
            Resources
          </span>

          <h1 className="mt-5 max-w-3xl text-[36px] font-bold leading-[1.08] tracking-[-0.025em] text-white sm:text-[46px]">
            Built for developers.
            <br />
            <span className="text-[#3395FF]">By developers.</span>
          </h1>

          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-slate-400">
            Everything you need to understand, verify and extend autonomous revenue recovery.
          </p>

          <div className="mt-9 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[
              { key: 'api', icon: Terminal, t: 'Integrations', s: 'How the pieces connect, end to end' },
              { key: 'api', icon: FileCode2, t: 'API reference', s: 'Every route this app exposes' },
              { key: 'webhooks', icon: Webhook, t: 'Webhooks', s: 'Signed Razorpay event ingestion' },
            ].map(({ key, icon: Icon, t, s }, i) => (
              <button
                key={`${key}-${i}`}
                onClick={() => openPanel(key)}
                className="group flex cursor-pointer items-start gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 text-left transition-all hover:-translate-y-0.5 hover:border-[#3395FF]/40 hover:bg-white/[0.06]"
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-[#7FB4FF]">
                  <Icon size={15} strokeWidth={2.2} />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-sm font-bold text-white">
                    {t}
                    <ArrowRight size={13} strokeWidth={2.5} className="text-slate-500 transition-transform group-hover:translate-x-0.5 group-hover:text-[#7FB4FF]" />
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-500">{s}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ══ SEE IT IN CODE ═════════════════════════════════════════════ */}
      <section className="rzp-container py-16 lg:py-20">
        <div className="mb-7 max-w-2xl">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
            Read the implementation
          </p>
          <h2 className="mt-2 text-[28px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[34px]">
            See it in code.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">
            Trace how a failed payment enters RecoverOS, gets diagnosed, passes policy, and
            becomes a recorded recovery decision. These are verbatim excerpts, not pseudocode.
          </p>
        </div>

        <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#070B16]">
          {/* File tabs */}
          <div className="flex flex-wrap items-center gap-1 border-b border-white/[0.07] bg-white/[0.02] px-3 py-2">
            {Object.entries(CODE).map(([key, c]) => (
              <button
                key={key}
                onClick={() => setCodeTab(key)}
                className={`cursor-pointer rounded-lg px-3 py-1.5 font-mono text-[11px] transition-colors ${
                  codeTab === key
                    ? 'bg-[#3395FF]/15 text-[#7FB4FF]'
                    : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
                }`}
              >
                {c.file.split('/').pop()}
              </button>
            ))}
            <span className="ml-auto flex items-center gap-2">
              <span className="hidden font-mono text-[10px] text-slate-600 sm:inline">{active.file}</span>
              <CopyButton text={active.body} id={`code-${codeTab}`} copied={copied} onCopy={copy} />
            </span>
          </div>

          <pre className="custom-scrollbar overflow-x-auto p-4 font-mono text-[11.5px] leading-[1.65] text-slate-300 sm:p-5 sm:text-xs">
            <code>{active.body}</code>
          </pre>

          <div className="border-t border-white/[0.07] bg-white/[0.02] px-4 py-2.5 sm:px-5">
            <p className="font-mono text-[10px] text-slate-500">{active.caption}</p>
          </div>
        </div>
      </section>

      {/* ══ ARCHITECTURE ═══════════════════════════════════════════════ */}
      <section className="border-y border-white/[0.07] bg-white/[0.015] py-16 lg:py-20">
        <div className="rzp-container">
          <div className="mb-8 max-w-2xl">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
              Architecture
            </p>
            <h2 className="mt-2 text-[28px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[34px]">
              Six stages, one path.
            </h2>
          </div>

          <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {STAGES.map((s) => {
              const Icon = s.icon;
              return (
                <li key={s.label} className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 transition-colors hover:border-[#3395FF]/30">
                  <div className="flex items-center justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-[#7FB4FF]">
                      <Icon size={15} strokeWidth={2.2} />
                    </span>
                    <span className="font-mono text-[11px] font-bold text-slate-600">{s.n}</span>
                  </div>
                  <h3 className="mt-3 text-base font-bold uppercase tracking-wide text-white">{s.label}</h3>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">{s.body}</p>
                  <p className="mt-3 truncate border-t border-white/[0.07] pt-2.5 font-mono text-[10px] text-slate-600">
                    {s.src}
                  </p>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {/* ══ PROOF, NOT PROMISES ════════════════════════════════════════ */}
      <section className="rzp-container py-16 lg:py-20">
        <div className="mb-8 max-w-2xl">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
            Credibility
          </p>
          <h2 className="mt-2 text-[28px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[34px]">
            Proof, not promises.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">
            One of these is re-checked in your browser right now. The rest are properties of the
            source and say so — a tick that means nothing is worse than no tick.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {TRUST.map((t) => {
            const Icon = t.icon;
            const badge = KIND_BADGE[t.kind];
            const isChain = t.key === 'chain';
            return (
              <div
                key={t.key}
                className={`rounded-2xl border p-5 ${
                  isChain ? 'border-emerald-400/25 bg-emerald-400/[0.06]' : 'border-white/[0.08] bg-white/[0.03]'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border ${
                    isChain ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300' : 'border-white/10 bg-white/[0.05] text-[#7FB4FF]'
                  }`}>
                    <Icon size={15} strokeWidth={2.2} />
                  </span>
                  <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${badge.cls}`}>
                    {isChain && checking ? 'checking…' : badge.text}
                  </span>
                </div>
                <h3 className="mt-3 text-sm font-bold text-white">{t.label}</h3>
                <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{t.detail}</p>

                {isChain && (
                  <p className="mt-3 border-t border-emerald-400/20 pt-2.5 font-mono text-[11px] font-bold text-emerald-300">
                    {checking ? 'verifying…'
                      : chain?.valid ? `${chain.entries_checked.toLocaleString('en-IN')} entries · chain intact`
                      : chain ? `chain broken at #${chain.first_broken_sequence}`
                      : 'chain unverified — API unreachable'}
                  </p>
                )}
                {t.src && (
                  <p className="mt-3 truncate border-t border-white/[0.07] pt-2.5 font-mono text-[10px] text-slate-600">{t.src}</p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ══ DEVELOPER RESOURCES ════════════════════════════════════════ */}
      <section className="border-y border-white/[0.07] bg-white/[0.015] py-16 lg:py-20">
        <div className="rzp-container">
          <div className="mb-8 max-w-2xl">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
              Reference
            </p>
            <h2 className="mt-2 text-[28px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[34px]">
              Developer resources.
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {RESOURCES.map(({ key, icon: Icon, title, body }) => (
              <button
                key={key}
                onClick={() => openPanel(key)}
                className={`group flex cursor-pointer flex-col rounded-2xl border p-5 text-left transition-all hover:-translate-y-0.5 ${
                  panel === key
                    ? 'border-[#3395FF]/45 bg-[#3395FF]/[0.08]'
                    : 'border-white/[0.08] bg-white/[0.03] hover:border-[#3395FF]/30'
                }`}
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-[#7FB4FF]">
                  <Icon size={15} strokeWidth={2.2} />
                </span>
                <span className="mt-3 text-sm font-bold text-white">{title}</span>
                <span className="mt-1 flex-1 text-[12px] leading-relaxed text-slate-400">{body}</span>
                <span className="mt-3 inline-flex items-center gap-1.5 font-mono text-[11px] font-bold text-[#7FB4FF]">
                  Open
                  <ArrowRight size={12} strokeWidth={2.5} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ══ REFERENCE PANELS ═══════════════════════════════════════════ */}
      <section ref={panelRef} className="rzp-container scroll-mt-20 py-16 lg:py-20">
        <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#070B16]">
          <div className="flex flex-wrap items-center gap-1 border-b border-white/[0.07] bg-white/[0.02] px-3 py-2">
            {RESOURCES.map(({ key, title }) => (
              <button
                key={key}
                onClick={() => setPanel(key)}
                className={`cursor-pointer rounded-lg px-3 py-1.5 font-mono text-[11px] transition-colors ${
                  panel === key ? 'bg-[#3395FF]/15 text-[#7FB4FF]' : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
                }`}
              >
                {title}
              </button>
            ))}
          </div>

          <div className="p-4 sm:p-6">
            {panel === 'architecture' && (
              <ol className="space-y-2.5">
                {STAGES.map((s) => (
                  <li key={s.label} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-white/[0.06] pb-2.5 last:border-b-0">
                    <span className="font-mono text-[11px] font-bold text-slate-600">{s.n}</span>
                    <span className="w-24 shrink-0 text-sm font-bold uppercase tracking-wide text-white">{s.label}</span>
                    <span className="min-w-[200px] flex-1 text-[12px] leading-relaxed text-slate-400">{s.body}</span>
                    <span className="font-mono text-[10px] text-slate-600">{s.src}</span>
                  </li>
                ))}
              </ol>
            )}

            {panel === 'matrix' && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left font-mono text-[11px]">
                  <thead className="border-b border-white/[0.08] text-slate-500">
                    <tr>
                      <th className="py-2 pr-4 font-normal">Failure class</th>
                      <th className="py-2 pr-4 font-normal">Typical reason</th>
                      <th className="py-2 pr-4 font-normal">Recovery rail</th>
                      <th className="py-2 font-normal">Assumed rate · config.py</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.05]">
                    {MATRIX.map((r) => (
                      <tr key={r.cls} className="hover:bg-white/[0.02]">
                        <td className={`py-2.5 pr-4 font-bold ${r.tone}`}>{r.cls}</td>
                        <td className="py-2.5 pr-4 text-slate-500">{r.reason}</td>
                        <td className="py-2.5 pr-4 text-slate-300">{r.rail}</td>
                        <td className="py-2.5 font-bold text-white">{r.rate}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
                  The rate column is the recovery probability each class is <em>assumed</em> to
                  have in <span className="font-mono text-slate-400">config.py</span>. It drives
                  the expected-value gate — it is not a measured outcome.
                </p>
              </div>
            )}

            {panel === 'webhooks' && (
              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-slate-500">
                    payment.failed — the event shape RecoverOS ingests
                  </span>
                  <CopyButton text={WEBHOOK_SAMPLE} id="wh" copied={copied} onCopy={copy} />
                </div>
                <pre className="custom-scrollbar overflow-x-auto rounded-xl border border-white/[0.07] bg-black/30 p-4 font-mono text-[11px] leading-relaxed text-slate-300">
                  <code>{WEBHOOK_SAMPLE}</code>
                </pre>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  An illustrative payload of the documented Razorpay shape, not a captured event.
                  The signature is verified over the exact received bytes before this is parsed —
                  see <span className="font-mono text-slate-400">routes/webhooks.py</span> in the
                  code panel above.
                </p>
              </div>
            )}

            {panel === 'api' && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left font-mono text-[11px]">
                  <thead className="border-b border-white/[0.08] text-slate-500">
                    <tr>
                      <th className="py-2 pr-3 font-normal">Method</th>
                      <th className="py-2 pr-4 font-normal">Route</th>
                      <th className="py-2 font-normal">Purpose</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.05]">
                    {ENDPOINTS.map((e) => (
                      <tr key={e.p} className="hover:bg-white/[0.02]">
                        <td className="py-2 pr-3">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            e.m === 'GET' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-[#3395FF]/15 text-[#7FB4FF]'
                          }`}>{e.m}</span>
                        </td>
                        <td className="py-2 pr-4 text-slate-200">{e.p}</td>
                        <td className="py-2 text-slate-500">{e.d}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
                  There is no published SDK package. RecoverOS is a FastAPI service — these routes
                  are the integration surface, and a WebSocket at{' '}
                  <span className="font-mono text-slate-400">/ws/dashboard</span> streams batch
                  progress and state changes.
                </p>
              </div>
            )}

            {panel === 'policy' && (
              <div>
                <pre className="custom-scrollbar overflow-x-auto rounded-xl border border-white/[0.07] bg-black/30 p-4 font-mono text-[11px] leading-relaxed text-slate-300">
                  <code>{CODE.policy.body}</code>
                </pre>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  Gates are evaluated cheapest-first and the first refusal wins. Nine of the ten
                  codes above are refusals; only <span className="font-mono text-slate-400">PROCEED</span>{' '}
                  authorises spend. Every one of them is written to the ledger with its reason.
                </p>
              </div>
            )}

            {panel === 'verify' && (
              <div>
                <div className="space-y-2">
                  {COMMANDS.map((c) => (
                    <div key={c.cmd} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-white/[0.07] bg-black/30 px-3 py-2.5">
                      <span className="font-mono text-[11px] text-emerald-300">$ {c.cmd}</span>
                      <span className="flex-1 text-[11px] text-slate-500">{c.d}</span>
                      <CopyButton text={c.cmd} id={c.cmd} copied={copied} onCopy={copy} />
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  Equivalent Python entry points live under{' '}
                  <span className="font-mono text-slate-400">backend/app/tools/</span> —
                  verify_ledger and tamper_demo among them.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ══ FOR THE REVIEWER ═══════════════════════════════════════════ */}
      <section className="rzp-container pb-16 lg:pb-20">
        <div className="relative overflow-hidden rounded-3xl border border-white/[0.08] bg-white/[0.03] p-6 sm:p-9">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_85%_20%,rgba(51,149,255,0.12),transparent_60%)]" />
          <div className="relative z-10">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-[#7FB4FF]">
              For the reviewer
            </p>
            <h2 className="mt-2 text-[26px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[32px]">
              Want to verify the claim?
            </h2>

            <div className="mt-7 grid grid-cols-1 gap-3 lg:grid-cols-3">
              <button
                onClick={() => onNavigateTab?.('overview')}
                className="group cursor-pointer rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-left transition-all hover:-translate-y-0.5 hover:border-[#3395FF]/40"
              >
                <span className="text-sm font-bold text-white">Explore the Command Center</span>
                <span className="mt-1.5 block text-[12px] leading-relaxed text-slate-400">
                  Real records, decisions, recovery outcomes and ledger evidence.
                </span>
                <span className="mt-3 inline-flex items-center gap-1.5 font-mono text-[11px] font-bold text-[#7FB4FF]">
                  Open <ArrowRight size={12} strokeWidth={2.5} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </button>

              <button
                onClick={() => onNavigateTab?.('console')}
                className="group cursor-pointer rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-left transition-all hover:-translate-y-0.5 hover:border-[#3395FF]/40"
              >
                <span className="text-sm font-bold text-white">Inspect the Engine</span>
                <span className="mt-1.5 block text-[12px] leading-relaxed text-slate-400">
                  How diagnosis, policy and recovery decisions are derived, against a real record.
                </span>
                <span className="mt-3 inline-flex items-center gap-1.5 font-mono text-[11px] font-bold text-[#7FB4FF]">
                  Open <ArrowRight size={12} strokeWidth={2.5} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </button>

              {/* Runs the real verification endpoint and reports what came back. */}
              <div className="rounded-2xl border border-emerald-400/25 bg-emerald-400/[0.06] p-5">
                <span className="text-sm font-bold text-white">Verify the ledger</span>
                <span className="mt-1.5 block text-[12px] leading-relaxed text-slate-400">
                  Recompute every entry hash and every link, right now.
                </span>
                <button
                  onClick={async () => { setReverify(true); await runVerify(); setReverify(false); }}
                  disabled={reverify || checking}
                  className="mt-3 inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 font-mono text-[11px] font-bold text-emerald-300 transition-colors hover:bg-emerald-400/20 disabled:opacity-60"
                >
                  {reverify || checking
                    ? <><Loader2 size={11} strokeWidth={2.6} className="animate-spin" />running…</>
                    : <>GET /api/ledger/verify</>}
                </button>
                <p className="mt-2.5 font-mono text-[11px] text-emerald-300">
                  {checking ? '…'
                    : chain?.valid ? `${chain.entries_checked.toLocaleString('en-IN')} entries · ${chain.reason}`
                    : chain ? `broken at #${chain.first_broken_sequence}`
                    : 'API unreachable'}
                </p>
              </div>
            </div>

            <p className="mt-7 border-t border-white/[0.07] pt-5 font-mono text-[10px] text-slate-500">
              RecoverOS is an independent Razorpay Buildathon entry (Track 03) built on Razorpay
              APIs in Test Mode. It is not a Razorpay product and moves no live money.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
