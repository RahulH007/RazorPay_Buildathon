/**
 * RecoverOS — Decision derivation
 *
 * Turns an /api/audit/{payment_id} response into the decision story the
 * Command Center renders: what was diagnosed and by whom, which policy gate
 * fired, what was spent, and how it ended.
 *
 * Every value here is read back out of ledger entries the backend already
 * writes. Nothing is synthesised: when a field cannot be derived from an
 * entry it comes back null, and the UI renders nothing rather than a
 * plausible-looking number. That rule is the whole point of the panel — it
 * claims to show what the ledger recorded, so it must not show anything else.
 *
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 */

/** Actions that actually reached the customer (or the PSP) and cost money. */
export const ACTED_ACTIONS = new Set([
  'WHATSAPP_LINK_SENT',
  'RETRY_SILENT_ATTEMPT',
  'MANDATE_RESEQUENCED',
  'VOICE_CALL_INITIATED',
]);

/**
 * Halts written outside the policy boundary. These are refusals too, they
 * just happen inside an action or at ingestion rather than in policy.py, so
 * they carry no POLICY_DECLINED_ prefix to read a reason code out of.
 */
export const HALT_ACTIONS = {
  WHY_WE_DIDNT_ACT: 'HARD_DECLINE',
  SUPPRESSED_CONSENT: 'CONSENT_WITHDRAWN',
  FRAUD_QUARANTINE: 'FRAUD_QUARANTINE',
  UNMAPPED_REASON_HELD_FOR_REVIEW: 'UNMAPPED_REASON',
  SETTLEMENT_MISMATCH_HELD: 'SETTLEMENT_MISMATCH',
  LIVE_LINK_BLOCKED_LOOPBACK_CALLBACK: 'LOOPBACK_CALLBACK',
  ESCALATED_TO_HUMAN: 'ESCALATED_TO_HUMAN',
};

/**
 * How each reason code should read to someone who has not read policy.py.
 *
 * `kind` separates three outcomes the UI must never blur together:
 *   acted   — policy approved the spend
 *   held    — a deliberate pause that resumes on its own
 *   stopped — automation is finished with this record
 */
export const REASON_CODES = {
  PROCEED: {
    kind: 'acted',
    label: 'Policy approved',
    headline: 'Policy approved recovery',
    blurb: 'Every gate passed. The action below was authorised and charged.',
  },
  HARD_DECLINE: {
    kind: 'stopped',
    label: 'Hard decline',
    headline: 'Policy blocked recovery: hard decline',
    blurb: 'Compliance-mandated halt. Zero retries, zero outreach, zero spend.',
  },
  HOLDOUT_CONTROL: {
    kind: 'held',
    label: 'Holdout control',
    headline: 'Held as control: measurement baseline',
    blurb: 'Deliberately untreated so recovery can be measured against a baseline.',
  },
  PROMISE_TO_PAY_PENDING: {
    kind: 'held',
    label: 'Promise to pay',
    headline: 'Deferred: customer named a payment date',
    blurb: 'The customer named a date. Deferred until then — a pause, not a stop.',
  },
  RETRY_CAP_REACHED: {
    kind: 'stopped',
    label: 'Attempt cap reached',
    headline: 'Policy stopped recovery: attempt cap reached',
    blurb: 'The per-record attempt cap binds before the ladder runs out.',
  },
  LADDER_EXHAUSTED: {
    kind: 'stopped',
    label: 'Ladder exhausted',
    headline: 'Policy stopped recovery: escalation ladder exhausted',
    blurb: 'Every escalation step for this failure class has been tried.',
  },
  CAC_CEILING: {
    kind: 'stopped',
    label: 'Cost ceiling',
    headline: 'Policy blocked recovery: cost ceiling',
    blurb: 'Another attempt would spend more than this invoice is worth recovering.',
  },
  NEGATIVE_EXPECTED_VALUE: {
    kind: 'stopped',
    label: 'Negative expected value',
    headline: 'Policy blocked recovery: negative expected value',
    blurb: 'The channel costs more than the margin it is expected to recover.',
  },
  CONSENT_WITHDRAWN: {
    kind: 'stopped',
    label: 'Consent withdrawn',
    headline: 'Policy blocked recovery: consent withdrawn',
    blurb: 'This contact opted out. Suppression outlives the individual payment.',
  },
  QUIET_HOURS_DEFERRED: {
    kind: 'held',
    label: 'Quiet hours',
    headline: 'Deferred: quiet hours',
    blurb: 'TRAI restricts promotional voice calls to 09:00–21:00 IST.',
  },
  FRAUD_QUARANTINE: {
    kind: 'stopped',
    label: 'Fraud quarantine',
    headline: 'Policy blocked recovery: fraud signal',
    blurb: 'Halted on a fraud signal, pending manual review. No consent was withdrawn.',
  },
  UNMAPPED_REASON: {
    kind: 'held',
    label: 'Unmapped error code',
    headline: 'Held before policy: unmapped error code',
    blurb: 'The error code is not in the rule map. Held for review rather than guessed at.',
  },
  SETTLEMENT_MISMATCH: {
    kind: 'stopped',
    label: 'Settlement mismatch',
    headline: 'Settlement held: did not reconcile',
    blurb: 'A settlement did not reconcile against the link that was issued.',
  },
  LOOPBACK_CALLBACK: {
    kind: 'stopped',
    label: 'Unreachable callback',
    headline: 'Blocked: Payment Link callback unreachable',
    blurb: 'A live link was refused because its callback names a loopback host.',
  },
  ESCALATED_TO_HUMAN: {
    kind: 'held',
    label: 'Escalated to a human',
    headline: 'Handed to the accounts team',
    blurb: 'Automation has handed this to the accounts team and stopped.',
  },
};

/**
 * The five words a reviewer should be able to read off the drawer in one
 * glance. `kind` is too coarse for this: a quiet-hours deferral and a holdout
 * are both "held", but one resumes at 09:00 and the other is never contacted
 * at all, and a panel that shows them identically hides the difference that
 * matters most.
 */
export const DECISION_STATUS = {
  RECOVERED: { code: 'RECOVERED', label: 'Recovered', tone: 'emerald' },
  PROCEED: { code: 'PROCEED', label: 'Proceed', tone: 'blue' },
  DEFER: { code: 'DEFER', label: 'Defer', tone: 'violet' },
  HOLD: { code: 'HOLD', label: 'Hold', tone: 'slate' },
  STOP: { code: 'STOP', label: 'Stop', tone: 'rose' },
};

/** Refusals that carry their own resume condition, rather than ending things. */
const DEFER_CODES = new Set(['QUIET_HOURS_DEFERRED', 'PROMISE_TO_PAY_PENDING']);

/**
 * The four outcomes the Command Center reports, as disjoint buckets.
 *
 * Disjointness is what lets them be stacked into one bar of GMV without
 * double-counting: a holdout control ends in FAILED_STOPPED but is not a
 * stop, so "held" is tested before "stopped" and wins.
 *
 * None of these labels calls a halt a failure, because none of them is one.
 * Every stop here is a policy decision the ledger recorded, and restraint is
 * an output of this system rather than an absence of one.
 */
export const OUTCOME_BUCKETS = {
  RECOVERED: { key: 'RECOVERED', label: 'Recovered', tone: 'emerald' },
  IN_PROGRESS: { key: 'IN_PROGRESS', label: 'In progress', tone: 'amber' },
  HELD: { key: 'HELD', label: 'Held & deferred', tone: 'violet' },
  STOPPED: { key: 'STOPPED', label: 'Stopped safely', tone: 'slate' },
};

export function outcomeBucket(record, decision) {
  if (record?.recovery_state === 'RECOVERED') return OUTCOME_BUCKETS.RECOVERED;
  if (decision && reasonMeta(decision.reasonCode).kind === 'held') return OUTCOME_BUCKETS.HELD;
  if (record?.recovery_state === 'FAILED_STOPPED') return OUTCOME_BUCKETS.STOPPED;
  return OUTCOME_BUCKETS.IN_PROGRESS;
}

export function decisionStatus(decision, record) {
  if (record?.recovery_state === 'RECOVERED') return DECISION_STATUS.RECOVERED;
  if (!decision) return DECISION_STATUS.HOLD;
  if (decision.acted) return DECISION_STATUS.PROCEED;
  if (DEFER_CODES.has(decision.reasonCode)) return DECISION_STATUS.DEFER;
  return reasonMeta(decision.reasonCode).kind === 'held'
    ? DECISION_STATUS.HOLD
    : DECISION_STATUS.STOP;
}

/**
 * Which consent channel a recovery channel routes through — the JS mirror of
 * CHANNEL_CONSENT_MAP in policy.py. Silent retry and the human queue are
 * absent because neither sends the customer anything, so neither is ever
 * tested for consent.
 */
const CHANNEL_CONSENT = {
  whatsapp_link: 'whatsapp',
  upi_resequence: 'whatsapp',
  hinglish_voice: 'voice',
};

/**
 * What became of the Payment Link, read only from what the ledger recorded.
 *
 * Demo runs write a placeholder URL and create nothing at Razorpay, so the
 * absence of a plink id is reported as a demo placeholder rather than dressed
 * up as a real link awaiting payment.
 */
export function linkStatus(decision) {
  if (!decision) return null;

  if (decision.paymentLinkId) {
    return {
      label: 'Paid',
      tone: 'emerald',
      note: decision.recoveryPaymentId
        ? `settled as ${decision.recoveryPaymentId}`
        : 'settled via payment_link.paid',
    };
  }

  if (!decision.paymentLinkUrl) return null;

  if (/\/demo_/.test(decision.paymentLinkUrl)) {
    return {
      label: 'Demo placeholder',
      tone: 'slate',
      note: 'no live Razorpay link was created in demo mode',
    };
  }

  return {
    label: 'Created, unpaid',
    tone: 'amber',
    note: 'awaiting a payment_link.paid webhook',
  };
}

/** Fallback so an unrecognised code still renders honestly. */
export function reasonMeta(code) {
  return (
    REASON_CODES[code] || {
      kind: 'stopped',
      label: code ? code.replace(/_/g, ' ').toLowerCase() : 'No decision recorded',
      blurb: null,
    }
  );
}

/**
 * The gates in policy.py, in the order policy.py evaluates them.
 *
 * Order is load-bearing rather than cosmetic: checks run cheapest-first and
 * the first refusal wins, so rendering them in this order is what shows a
 * reviewer that the recorded reason is the most fundamental one rather than
 * whichever happened to be evaluated last.
 */
export const POLICY_GATES = [
  { id: 'hard_decline', label: 'Not a hard decline', codes: ['HARD_DECLINE'] },
  { id: 'holdout', label: 'Not in the holdout arm', codes: ['HOLDOUT_CONTROL'] },
  { id: 'promise', label: 'No promise to pay pending', codes: ['PROMISE_TO_PAY_PENDING'] },
  { id: 'attempt_cap', label: 'Within the attempt cap', codes: ['RETRY_CAP_REACHED'] },
  { id: 'ladder', label: 'Escalation ladder has a step left', codes: ['LADDER_EXHAUSTED'] },
  { id: 'cac', label: 'Within the cost ceiling', codes: ['CAC_CEILING'] },
  { id: 'ev', label: 'Worth more than it costs', codes: ['NEGATIVE_EXPECTED_VALUE'] },
  // policy.py runs these as one is_suppressed() call, but consent.py tests
  // opt-out first and quiet hours second, and only ever tests quiet hours on a
  // voice channel. Showing them as two ordered rows says which of the two
  // actually blocked a send; folding them into one row cannot.
  { id: 'consent', label: 'Consent held', codes: ['CONSENT_WITHDRAWN'] },
  { id: 'quiet_hours', label: 'Inside calling hours', codes: ['QUIET_HOURS_DEFERRED'] },
];

/**
 * Split a trail into the current run and everything before it.
 *
 * The same payment_id is re-ingested by every batch, so one trail can hold
 * seven runs and forty-four entries. Showing them as one flat list reads as a
 * single incoherent story, so the current run is what the drawer opens on.
 */
export function currentRun(trail = []) {
  let start = 0;
  for (let i = trail.length - 1; i >= 0; i -= 1) {
    if (trail[i].action === 'RECORD_INGESTED') {
      start = i;
      break;
    }
  }
  return { run: trail.slice(start), earlier: trail.slice(0, start) };
}

const num = (v) => (v == null ? null : Number(v));

/**
 * Pull the figures policy.py already wrote into its own reason string.
 *
 * Parsing prose is ordinarily a bad idea; it is the right one here because
 * these strings are the hashed ledger content. Re-deriving the numbers in the
 * browser would let the panel disagree with the entry it claims to be
 * displaying. Every match is optional and every miss degrades to null.
 */
export function parsePolicyNumbers(details = '') {
  const out = {};

  const proceed = details.match(
    /Attempt (\d+) of (\d+) for (\w+): (\w+) at (\d+)p, within the (\d+)p ceiling and worth an expected (\d+)p/
  );
  if (proceed) {
    out.attempt = num(proceed[1]);
    out.ladderLength = num(proceed[2]);
    out.channel = proceed[4];
    out.costPaise = num(proceed[5]);
    out.ceilingPaise = num(proceed[6]);
    out.expectedPaise = num(proceed[7]);
  }

  const cac = details.match(
    /Spending (\d+)p on (\w+) would take total spend to (\d+)p against a ceiling of (\d+)p/
  );
  if (cac) {
    out.costPaise = num(cac[1]);
    out.channel = cac[2];
    out.spentAfterPaise = num(cac[3]);
    out.ceilingPaise = num(cac[4]);
  }

  const ev = details.match(
    /(\w+) costs (\d+)p but the expected margin recovered is only (\d+)p/
  );
  if (ev) {
    out.channel = ev[1];
    out.costPaise = num(ev[2]);
    out.expectedPaise = num(ev[3]);
  }

  const cap = details.match(/Attempt cap reached: (\d+) of a maximum (\d+)/);
  if (cap) {
    out.attempt = num(cap[1]);
    out.maxRetries = num(cap[2]);
  }

  const ladder = details.match(/exhausted after (\d+) step\(s\): (.+?)\./);
  if (ladder) {
    out.ladderLength = num(ladder[1]);
    out.ladderSteps = ladder[2].split(' -> ');
  }

  const deferred = details.match(/Deferred to ([^.]+)/);
  if (deferred) out.deferredUntil = deferred[1].trim();

  const promised = details.match(/pay by (\d{4}-\d{2}-\d{2})/);
  if (promised) out.promisedDate = promised[1];

  return out;
}

/** Strip the marker the ledger uses to make a refusal greppable. */
export function cleanReason(details = '') {
  return details.replace(/^WHY_WE_DIDNT_ACT:\s*/, '').trim();
}

const lastMatching = (entries, pred) => {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    if (pred(entries[i])) return entries[i];
  }
  return null;
};

/**
 * The whole decision for one payment, as recorded.
 *
 * @param {object} auditData response body from GET /api/audit/{payment_id}
 * @returns {object|null}
 */
export function deriveDecision(auditData) {
  const trail = auditData?.audit_trail;
  if (!Array.isArray(trail) || trail.length === 0) return null;

  const { run, earlier } = currentRun(trail);

  // --- Diagnosis ------------------------------------------------------
  const classified = lastMatching(run, (e) => e.action.startsWith('CLASSIFIED_'));
  const llmDiagnosed = lastMatching(run, (e) => e.action === 'FAILURE_DIAGNOSED_LLM');
  const diagnosis = llmDiagnosed || classified;
  const confidenceEntry = lastMatching(run, (e) => e.llm_metadata?.confidence != null);

  // --- Action ---------------------------------------------------------
  const actions = run.filter((e) => ACTED_ACTIONS.has(e.action));
  const lastAction = actions.length ? actions[actions.length - 1] : null;

  // --- Verdict --------------------------------------------------------
  // A record can act and then be refused on the next rung (send WhatsApp,
  // then be blocked from the voice call by quiet hours). Sequence number
  // decides which came last, so the drawer reports the standing decision
  // rather than the most dramatic one.
  const declined = lastMatching(run, (e) => e.action.startsWith('POLICY_DECLINED_'));
  const halted = lastMatching(run, (e) => e.action in HALT_ACTIONS);
  const approved = lastMatching(run, (e) => e.action === 'STATE_DIAGNOSED_TO_INTERVENING');

  const candidates = [
    declined && {
      entry: declined,
      code: declined.action.replace('POLICY_DECLINED_', ''),
      acted: false,
    },
    halted && { entry: halted, code: HALT_ACTIONS[halted.action], acted: false },
    approved && { entry: approved, code: 'PROCEED', acted: true },
  ].filter(Boolean);

  candidates.sort((a, b) => a.entry.sequence_no - b.entry.sequence_no);
  const verdict = candidates.length ? candidates[candidates.length - 1] : null;

  const reasonCode = verdict?.code || null;
  const reasonText = verdict ? cleanReason(verdict.entry.details || '') : null;
  const numbers = parsePolicyNumbers(verdict?.entry?.details || '');

  // The approval string carries the ladder position and ceiling even when a
  // later rung was refused, so read it too and let the refusal win on
  // conflict.
  const approvalNumbers = approved ? parsePolicyNumbers(approved.details || '') : {};
  const policy = { ...approvalNumbers, ...numbers };

  // --- Outcome --------------------------------------------------------
  const terminal = lastMatching(
    run,
    (e) => e.action.endsWith('_TO_RECOVERED') || e.action.endsWith('_TO_FAILED_STOPPED')
  );

  // --- Correlation ids -------------------------------------------------
  // Only ever read back from an entry. A demo run creates no plink, and the
  // absence must show as absence.
  const settled = lastMatching(run, (e) => e.action.endsWith('_TO_RECOVERED'));
  const linkIdMatch = settled?.details?.match(/Payment Link (\w+)/);
  const recoveryPaymentMatch = settled?.details?.match(/\(new payment (\w+)\)/);
  const linkUrlMatch = lastAction?.details?.match(/(https?:\/\/[^\s|]+)/);

  const spendPaise = run.reduce((sum, e) => sum + (e.cost_paise || 0), 0);
  const rejections = run.filter((e) => e.action === 'LLM_OUTPUT_REJECTED');

  return {
    paymentId: auditData.payment_id,
    run,
    earlier,
    earlierRunCount: earlier.filter((e) => e.action === 'RECORD_INGESTED').length,

    diagnosis: diagnosis
      ? {
          text: diagnosis.details,
          actor: diagnosis.actor,
          failureClass: classified?.action.replace('CLASSIFIED_', '') || null,
          llm: diagnosis.llm_metadata || null,
        }
      : null,
    confidence: confidenceEntry?.llm_metadata?.confidence ?? null,
    confidenceSource: confidenceEntry?.action || null,

    acted: verdict?.acted ?? false,
    // Did the policy engine run at all on this record? A payment held at
    // ingestion — an unmapped error code, a settlement that would not
    // reconcile — never reaches policy.py, and its gates must not be drawn as
    // having passed. Either an approval or a refusal proves evaluation.
    policyEvaluated: Boolean(approved || declined),
    reasonCode,
    reasonText,
    reasonEntry: verdict?.entry || null,
    policy,

    action: lastAction
      ? {
          entry: lastAction,
          channel: lastAction.action,
          attempts: actions.length,
          llm: lastAction.llm_metadata || null,
        }
      : null,
    rejections: rejections.length,

    spendPaise,
    spendInr: spendPaise / 100,

    outcomeEntry: terminal || null,
    paymentLinkId: linkIdMatch?.[1] || null,
    recoveryPaymentId: recoveryPaymentMatch?.[1] || null,
    paymentLinkUrl: linkUrlMatch?.[1] || null,

    lastTimestamp: run.length ? run[run.length - 1].timestamp : null,
    verification: auditData.verification || null,
    totalEntries: auditData.total_entries ?? trail.length,
  };
}

const rupees = (paise) =>
  paise == null
    ? null
    : `₹${(paise / 100).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;

/** One short, factual line per gate — only when the ledger supplied one. */
function gateDetail(id, decision) {
  const p = decision.policy || {};
  switch (id) {
    case 'holdout':
      return decision.reasonCode === 'HOLDOUT_CONTROL' ? 'control arm' : 'treated arm';
    case 'promise':
      return p.promisedDate ? `promised ${p.promisedDate}` : null;
    case 'attempt_cap':
      if (p.attempt != null && p.maxRetries != null) {
        return `${p.attempt} of ${p.maxRetries} attempts`;
      }
      return p.attempt != null ? `attempt ${p.attempt}` : null;
    case 'ladder':
      if (p.ladderSteps) return p.ladderSteps.join(' → ');
      if (p.attempt != null && p.ladderLength != null) {
        return `step ${p.attempt} of ${p.ladderLength}${p.channel ? ` → ${p.channel}` : ''}`;
      }
      return p.channel || null;
    case 'cac': {
      const spent = p.spentAfterPaise ?? decision.spendPaise;
      if (p.ceilingPaise == null) return null;
      return `${rupees(spent)} of ${rupees(p.ceilingPaise)} ceiling`;
    }
    case 'ev':
      if (p.expectedPaise == null) return null;
      return `expected ${rupees(p.expectedPaise)} vs cost ${rupees(p.costPaise ?? 0)}`;
    case 'consent':
      if (decision.reasonCode === 'CONSENT_WITHDRAWN') return 'opted out';
      return p.channel && !CHANNEL_CONSENT[p.channel] ? 'no customer contact on this channel' : null;
    case 'quiet_hours':
      if (p.deferredUntil) return `deferred to ${p.deferredUntil}`;
      if (p.channel && CHANNEL_CONSENT[p.channel] !== 'voice') return 'voice channels only';
      return null;
    default:
      return null;
  }
}

/**
 * Gates that policy.py reaches but never actually tests for this channel: a
 * silent retry contacts nobody, so consent does not apply to it, and quiet
 * hours constrain voice alone. Marking these "passed" would credit the engine
 * with a check it did not perform.
 */
function gateIsInapplicable(gateId, decision) {
  const channel = decision.policy?.channel;
  if (!channel) return false;
  if (gateId === 'consent') return !CHANNEL_CONSENT[channel];
  if (gateId === 'quiet_hours') return CHANNEL_CONSENT[channel] !== 'voice';
  return false;
}

/**
 * The gate list for one decision: which passed, which fired, which never ran.
 *
 * Gates after the one that fired are marked `skipped` rather than `passed`,
 * because policy.py returns on the first refusal and never evaluates them.
 * Claiming they passed would be a small lie about how the engine works.
 */
export function buildPolicyChecks(decision) {
  if (!decision) return [];

  const firedIndex = decision.acted
    ? -1
    : POLICY_GATES.findIndex((g) => g.codes.includes(decision.reasonCode));

  // A halt written outside policy.py — an unmapped error code held at
  // ingestion, a settlement that would not reconcile — matches no gate. If
  // policy never ran, every gate is unevaluated: drawing eight green ticks
  // would assert eight checks that never happened.
  const neverEvaluated = firedIndex < 0 && !decision.policyEvaluated;

  return POLICY_GATES.map((gate, i) => {
    let status = 'passed';
    if (neverEvaluated) {
      status = 'skipped';
    } else if (firedIndex >= 0 && i === firedIndex) {
      status = 'fired';
    } else if (firedIndex >= 0 && i > firedIndex) {
      status = 'skipped';
    } else if (gateIsInapplicable(gate.id, decision)) {
      status = 'skipped';
    }
    return { ...gate, status, detail: gateDetail(gate.id, decision) };
  });
}

export { rupees as formatPaise };
