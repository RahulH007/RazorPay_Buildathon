# RecoverOS → Buildathon-Winnable: Provable Recovery

## Context

The current build has the right shape for Track 03 (detect → diagnose → intervene → audit) and genuinely good bones: a strict FSM in `backend/app/state_machine.py`, 34 passing tests, prompt-injection sanitization, and Hindi banned-phrase filtering. But a review of the running code found that the three claims the track's bar actually grades are not backed by the implementation:

- **"Measured money recovered"** is `random.random() < base_rate` (`recovery_simulator.py:154`) against a hardcoded constant. The outcome does not depend on anything the agent did. Two runs produced 34% and 56%.
- **"Stopping rules"** never fire. An instrumented 50-record batch produced **zero** `GUARDRAIL_HALT`, `RETRY_CAP`, `CAC_CEILING`, or opt-out rows. `run_all_guards` is called once per record before the first action, so counters are always 0; `check_opt_out` is dead code (never called with a `message`); `log_hard_decline` never executes because the simulator skips terminal records.
- **"Audit trail"** is a plain table with an autoincrement PK. README calls it "cryptographic."

Plus: doc drift (3 README endpoints don't exist, 3 paths wrong, `LICENSE` missing), a demo-day landmine (pressing the batch button 4× collapses the best-performing class via stale cross-run retry counts), dashboard cost inflating every run (₹24.50 → ₹49 → ₹73.50), per-payment instead of per-customer opt-out, and an LLM path that fires on 0 of 50 records.

**The decision:** rather than patch these as bugs, make *provable auditability* the product. The thesis becomes:

> **RecoverOS can prove what it did, what it spent, and why it stopped — and you can verify it yourself in one command.**

This is deliberately chosen for an AI-first review round. An AI screening hundreds of submissions rewards **verifiable specificity** over impressive adjectives, and punishes internal contradiction between README and code. "Tamper one row, run `make verify-ledger`, watch it name the broken link" is checkable. "34% recovery rate" is not. Every workstream below either makes a claim true or makes it checkable.

**Constraints:** 1–2 weeks. Razorpay Test Mode keys + public tunnel available. Deliverables are a GitHub repo, a 5-minute pitch video, and a submission form with fields for Objectives, What It Solves, and Build Challenges.

---

## Success criteria

The submission is done when a reviewer can, from a clean clone:

1. Run one command and get a batch result **identical to the numbers in the README** (seeded, deterministic).
2. Run one command that verifies the entire audit ledger cryptographically and prints the chain head hash.
3. Run a tamper script and watch verification fail, naming the exact broken sequence number.
4. See stopping rules **actually firing** in the run output, with reason codes and counts.
5. See a real ₹1 Razorpay test payment move a card to RECOVERED via a signature-verified webhook.
6. Find no claim in the README that isn't backed by code, and an explicit table of what is real vs. simulated.

---

## Workstream 1 — Tamper-evident ledger (the headline)

**New: `backend/app/ledger.py`**

A single global hash chain over every audit entry.

- `canonical(entry) -> bytes` — deterministic serialization. See **Hash preimage discipline** below; this is the part that must be right before anything writes through the ledger.
- `compute_entry_hash(prev_hash, entry_fields) -> str` — SHA-256 over the length-prefixed encoding of `prev_hash`, `sequence_no`, `payment_id`, `timestamp_us`, `action`, `actor`, `details`, `cost_paise`.

### Hash preimage discipline

**Rule: hash only integers and length-prefixed bytes. Never floats, never formatted datetimes.**

**1. Length-prefix every field.** Plain concatenation collides — verified: `("ab","c")` and `("a","bc")` both hash to `ba7816bf8f01cfea`. Content can shift between adjacent fields with the hash unchanged.

```python
def _f(b: bytes) -> bytes:
    return len(b).to_bytes(4, "big") + b
preimage = b"".join(_f(x) for x in fields)
```

**2. Money as integer paise — never float.** Python's shortest-round-trip repr means `24.50` is not actually producible (`json.dumps(24.5) == '24.5'` on every platform), so the naive worry is unfounded. The real hazards are float *arithmetic* (`0.1 + 0.2 == 0.30000000000000004`) and cross-language verifier disagreement.

Change `models.py:69` `cost_incurred_inr = Column(Float)` → `cost_incurred_paise = Column(Integer)`. This aligns with the convention the codebase already uses correctly for `amount` (`models.py:22`, "Amount in paise") — cost was the inconsistent one. `CHANNEL_COSTS` becomes `{"AUTH_FRICTION": 50, "B2B_RECEIVABLE": 200, ...}` in paise. All arithmetic integer; divide by 100 only at the presentation layer.

Bonus: the CAC ceiling becomes exact integer comparison with no division —
`total_cost_paise * 100 >= amount_paise * CAC_CEILING_PERCENT`.

**3. Timestamps as integer microseconds — never a formatted string.** SQLite stores `DateTime` as TEXT; a raw read returns `'2026-08-25 07:12:50.651868+00:00'`, and the exact format depends on the adapter. Current code also writes tz-aware `datetime.now(timezone.utc)` into a column not declared `timezone=True`. Store `timestamp_us = Column(Integer)` (microseconds since Unix epoch) and hash that; keep a derived display value if wanted, but never hash it.

**4. Normalize text defensively.** `details` carries ₹ and Hinglish. Spot-checks showed the strings in use are already NFC-stable, so this is insurance rather than an active bug — but customer names arrive from webhooks, so apply `unicodedata.normalize("NFC", s).encode("utf-8")` on every text field before hashing.

**Test (`test_ledger.py`):** assert a golden preimage byte-for-byte against a committed fixture, so any future change to the encoding fails loudly instead of silently invalidating every prior hash.
- `append_entry(db, ...)` — reads current chain head, computes hash, inserts, retries on conflict (see concurrency below).
- `verify_chain(db, payment_id=None) -> VerificationResult` — walks the chain, returns `{valid, entries_checked, head_hash, first_broken_sequence, reason}`.

**Modify `backend/app/models.py`** — `AuditTrailEntry` gains `sequence_no` (**UNIQUE**, monotonic), `prev_hash` (**UNIQUE**), `entry_hash`.

Genesis uses the sentinel `prev_hash = "0" * 64`, **not** `NULL`. With `UNIQUE` on `prev_hash`, the sentinel means exactly one row can ever be the chain root; SQLite permits multiple `NULL`s under a unique index, which would silently allow multiple genesis rows and therefore multiple valid-looking chains. The sentinel makes "there is one chain" a schema guarantee.

### Concurrency: enforce the invariant in the schema, not in the writer

A `threading.Lock` is the wrong primitive here. Single-process it's already nearly redundant (`append_entry` is synchronous with no await points, and the batch runs on one event loop thread), and it straddles two execution contexts — the event loop for async paths, the threadpool for sync endpoints. Multi-process (`uvicorn --workers > 1`) it does nothing at all: two workers read the same head and fork the chain.

**Primary mechanism — `UNIQUE` on `prev_hash`.** A chain fork *requires* two rows sharing a `prev_hash`. The unique index makes that structurally impossible. The loser of a race gets `IntegrityError`, refetches the head, and retries (bounded, ~3 attempts). This is optimistic concurrency, and it's the right choice for this thesis: the guarantee stops depending on the writer holding a lock correctly and becomes a property the database enforces. State it that way in the README — *"the invariant is enforced by the schema, not by our code"* — because that's the sentence an auditor cares about.

**Secondary — reduce retry churn.** Modify `backend/app/database.py` (currently no WAL, no busy timeout, `database.py:14-18`):
- `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL` via a `connect` event listener.
- `BEGIN IMMEDIATE` requires defeating pysqlite's legacy implicit transaction handling first — set `dbapi_conn.isolation_level = None` on `connect`, then emit `BEGIN IMMEDIATE` on the `begin` event. Without the first step the second silently does nothing, which is the classic footgun.

**Test:** spawn 4 concurrent writers appending 50 entries each; assert 200 entries, no sequence gaps, chain verifies, and at least one retry was observed.

**Append-only enforcement** — SQLAlchemy `before_update` / `before_delete` event listeners on `AuditTrailEntry` that raise, plus SQLite triggers created in the `lifespan` hook of `main.py` so the guarantee survives direct DB access. The triggers are what make the tamper demo meaningful.

**Modify `backend/app/state_machine.py`** — both `log_audit()` and `transition_state()` route their inserts through `ledger.append_entry()`. Keep the existing signatures so nothing else changes.

**New: `backend/app/routes/ledger.py`**
- `GET /api/ledger/verify` — full chain
- `GET /api/audit/{payment_id}/verify` — per-payment slice
- `GET /api/ledger/head` — current head hash + entry count

**New CLI: `backend/app/tools/verify_ledger.py`** and **`backend/app/tools/tamper_demo.py`**. The tamper demo edits one `details` field via raw sqlite3, then runs verification and prints the failure. This is the moment in the video.

**Tests: `backend/tests/test_ledger.py`** — chain validity after a full batch; detects modified field; detects deleted row (sequence gap); detects reordering; `ORM update raises`.

---

## Workstream 2 — Consent registry (compliance made real)

Today opt-out marks one payment `FAILED_STOPPED` (`routes/recovery.py:81`, `voice_pipeline.py:131`). The same phone on another failed payment gets contacted again — the exact thing opt-out exists to prevent.

**New: `backend/app/consent.py` + `ConsentRecord` model**

- Keyed on `contact_hash = sha256(normalized_phone)` — never store the raw number in the consent table. This is a real privacy design and a good line in the pitch.
- Per-channel state (`whatsapp` / `voice` / `sms`), with `source` (dtmf_9, whatsapp_reply, api, merchant_upload), `recorded_at`, and the `payment_id` where consent was withdrawn.
- `is_suppressed(db, phone, channel) -> (bool, reason)`
- `record_opt_out(db, phone, channel, source, payment_id)` — writes both the registry row and a ledger entry.
- **Quiet hours** (TRAI: no marketing voice calls 21:00–09:00 IST) — `in_quiet_hours(now)`. Cheap to implement, instantly credible to an Indian fintech judge, and it produces a *deferral* rather than a stop, which shows nuance.

**Modify `backend/app/recovery_actions.py`** — every outbound (`send_whatsapp_link`, `initiate_voice_recovery`, `resequence_mandate`) calls `is_suppressed()` first and writes a `SUPPRESSED_CONSENT` ledger entry on block. This must be inside the action functions, not just in `execute_recovery`, so it cannot be bypassed.

**Wire up the dead code** — `check_opt_out()` in `guardrails.py` gets called from a new inbound-message path (`POST /api/recovery/{id}/reply`) that feeds the WhatsApp simulator. Fix the false-positive patterns: `\bno\b` and `\bnahi\b` currently fire on *"I have no money right now, will pay tomorrow"* and *"abhi nahi, kal karunga"* — both payment intent, not opt-out. Require stop-phrase context (`nahi chahiye`, `mat bhejo`) rather than bare negation.

**Demo moment:** opt out on payment A → payment B for the same phone is blocked, with the ledger entry proving it.

---

## Workstream 3 — Make the stopping rules fire

**New: `backend/app/policy.py`** — one place that decides *whether to act, on what channel, and whether to stop*, and records the decision either way.

- `ATTEMPT_LADDER` per failure class, so `MAX_RETRIES = 3` is actually reachable:
  - `TRANSIENT_TECHNICAL`: silent retry ×3 with backoff
  - `AUTH_FRICTION`: WhatsApp → 24h → WhatsApp reminder → stop
  - `MANDATE_BALANCE`: nudge → resequence to salary date → stop
  - `B2B_RECEIVABLE`: WhatsApp → voice → human queue
  - `HARD_DECLINE`: zero attempts, `WHY_WE_DIDNT_ACT` recorded
- `decide_next_action(db, record) -> PolicyDecision` returning either an action or a **reason code** (`RETRY_CAP_REACHED`, `CAC_CEILING`, `CONSENT_WITHDRAWN`, `QUIET_HOURS_DEFERRED`, `HARD_DECLINE`, `HOLDOUT_CONTROL`, `NEGATIVE_EXPECTED_VALUE`).
- **Every decision — including non-action — writes a ledger entry.** This is the audit thesis applied to the decision layer.

**Modify `backend/app/recovery_actions.py`** — `run_all_guards` re-runs before *every* attempt, not once (`recovery_actions.py:206`).

**Modify `backend/app/guardrails.py`** — scope `check_retry_cap` and `check_cac_ceiling` to the current `batch_id`/episode. This fixes the verified landmine where run #4 trips stale retry counts and silently kills all 15 `TRANSIENT_TECHNICAL` records (`DIAGNOSED_TO_FAILED_STOPPED` went 4 → 31 across four runs).

**Modify `backend/app/recovery_simulator.py`** — stop skipping `execute_recovery` for terminal records (`recovery_simulator.py:144`) so `log_hard_decline` / `WHY_WE_DIDNT_ACT` actually runs.

**Modify `backend/data/test_batch_50.json` → grow to ~60 records**, deliberately seeded so each guard demonstrably trips:
- 3 records that hit the retry cap
- 3 low-value records where WhatsApp + voice would breach the 15% CAC ceiling
- 2 sharing a phone with an opted-out contact
- 3 arriving during quiet hours
- 6 with **free-text error descriptions not in `RULE_MAP`** so the Gemini slow path finally fires (currently 0 of 50), plus `customer_reply` fields in Hinglish for `parse_customer_reply`
- Document `DEMO_MODE=false` in `.env.example` — it's absent, so Gemini never runs even with a valid key.

---

## Workstream 4 — Real Razorpay settlement loop

The project blueprint (`recoveros_blueprint.md:541,546`) lists this unchecked. It's the strongest anti-vaporware signal available.

**Modify `backend/app/routes/webhooks.py`:**

- **Fail closed.** `verify_webhook_signature` currently returns `True` when the secret is unset (`webhooks.py:20`). Replace with an explicit `ALLOW_UNSIGNED_WEBHOOKS` config flag defaulting to `false`; log loudly when enabled. This is the actual live vulnerability in the current code.

- **Signature verification — the failure modes that actually bite.** The raw-body ordering is already correct: `webhooks.py:39-45` reads `await request.body()` before `await request.json()`, Starlette caches the body, and the only registered middleware is CORS, which never touches the stream. Don't "fix" this. Guard the real risks instead:
  - **Wrong secret.** The webhook secret is configured *per endpoint* in the Razorpay dashboard and is **not** `RAZORPAY_KEY_SECRET`. `config.py:12-14` holds both one line apart. This is the most common cause of test-mode signature mismatch. Add a startup assertion that `RAZORPAY_WEBHOOK_SECRET != RAZORPAY_KEY_SECRET` and fail loudly if they match.
  - **Verify against exact received bytes** — never re-serialize the parsed JSON.
  - **Regression test** (`backend/tests/test_webhook_security.py`) with a committed fixture: fixed payload + fixed secret + precomputed expected signature. Assert valid passes, tampered body fails, missing header fails, and — critically — that verification still passes with middleware registered. That test is what stops a future logging middleware from silently breaking the stream.

- **Idempotency** — new `WebhookEvent` table keyed on `x-razorpay-event-id`; replayed events return `{"status": "duplicate"}` without re-transitioning. Razorpay retries, so this is a real correctness requirement, not a nicety.

- **Implement `payment.failed` ingestion** — currently returns `"acknowledged"` and does nothing (`webhooks.py:62`), while the architecture diagram puts it at box ①. Route it through the same `ingest_record` → `classify` → `policy` path the batch uses.

- Record the verified signature and event ID in the ledger entry, so the audit trail proves the settlement was authenticated.

**Modify `backend/app/recovery_actions.py`** — `send_whatsapp_link` already has the real `client.payment_link.create` path behind `DEMO_MODE` (`recovery_actions.py:78-84`). Fix the hardcoded `callback_url` to a config value, and add `notes={"recoveros_payment_id": record.payment_id}` so settlement matching is exact rather than by amount.

**New: `docs/LIVE_MODE.md`** — tunnel setup, webhook registration in the Razorpay dashboard, and the exact ₹1 test walkthrough.

**Demo moment:** scan the UPI QR on your phone, pay ₹1, watch the Kanban card flip to RECOVERED and the ledger gain a signature-verified entry.

---

## Workstream 5 — Honest, reproducible measurement

Even with auditability as the headline, the money number must be defensible — and under this thesis, *"we can prove this recovery was caused by us"* is the same argument.

**New: `backend/app/outcome_engine.py`** — replaces `random.random()`.

Each dataset record carries explicit counterfactual behavior:
```json
"behavior": {
  "natural_recovery_at_hours": 18,
  "responds_to": {"whatsapp": 0.6, "voice": 0.9, "silent_retry": 1.0},
  "p2p_keeps_promise": true
}
```
The engine replays a clock: did the intervention land *before* the natural-recovery time, and did the customer respond to that channel? Same input → same output, every run. A single `RECOVEROS_SEED` (default fixed, printed in every result header) governs any residual sampling.

**Holdout — assign by contact, stratify by class.** `config.HOLDOUT_PERCENT = 20`, assignment deterministic via `sha256(contact_hash + seed) % 100 < 20` — **not** `payment_id`. The current dataset has 50 unique phones so per-payment hashing looks safe today, but Workstream 3 deliberately adds records sharing a phone with an opted-out contact, which would put the same person in both arms and contaminate both the lift estimate and the consent story. Contact-level assignment also makes the randomization unit match the consent unit.

Stratify within `failure_class` so a 6-record class doesn't randomly land 0 or 5 in control. Holdout records get a `HOLDOUT_CONTROL` policy decision and are never contacted.

**Separate the demo from the measurement.** At ~60 records a 20% holdout gives N=12 controls — a confidence interval wide enough to swallow any point estimate. Under a thesis of *provable* rigor, an unfalsifiable statistical claim is worse than no claim. So run two things:

| | Demo batch | Measurement run |
|---|---|---|
| Size | ~60 records | ~2,000 synthetic contacts |
| Purpose | Watchable, seeded, shown in the video | The defensible lift number |
| Output | Live dashboard | `results/lift_analysis.md`, committed |
| Reporting | Mechanism, guard firings | Lift **with a 95% CI**, across multiple seeds |

New: `backend/app/tools/run_measurement.py` — generates the larger population from the same behavior model, runs headless across N seeds, reports mean lift and CI. Report the holdout in **contacts**, not payments, since that's the randomization unit.

**Modify `backend/app/routes/metrics.py`** — replace the single misleading `net_roi = recovered_gmv − channel_cost` (`metrics.py:56`) with a decomposition:

| Field | Meaning |
|---|---|
| `gross_recovered_gmv` | All recovered, treated + control |
| `control_recovery_rate` | Baseline from the holdout |
| `incremental_recovered_gmv` | Lift attributable to the agent |
| `merchant_margin_assumed` | **Stated explicitly** (default 20%) |
| `attributable_value` | `incremental × margin` |
| `channel_spend` | From the ledger, **scoped by `batch_id`** |
| `net_value` | `attributable_value − channel_spend` |

All monetary fields are integer paise end-to-end (see Workstream 1, *Hash preimage discipline*); convert to rupees only when rendering.

Fix the verified inflation bug: `metrics.py:53` sums audit cost with no batch filter while GMV stays pinned to the same records.

The README headline becomes a sentence no other team can write — stated from the **measurement run**, with the demo batch cited separately as the mechanism:

> *"Across 2,000 contacts and 10 seeds: treated group recovered 56%, control recovered 31% on its own. **Incremental lift 25pp (95% CI: 21–29pp) — ₹47,200 that would not have arrived otherwise, for ₹24.50 of spend, every rupee traceable to a hash-chained ledger entry you can verify in one command.**"*

Quote the CI, always. A point estimate invites the question; a CI answers it before it's asked.

---

## Workstream 6 — Frontend: surface the proof

The UI currently shows recovery. It needs to show *provability*.

- **`components/AuditInspector/AuditModal.jsx`** — render `sequence_no`, truncated `entry_hash`, and a green/red chain-verified badge per entry. Add a "Verify chain" button hitting `/api/audit/{id}/verify`.
- **New `components/Ledger/LedgerPanel.jsx`** — live chain head hash, total entries, verification status. A monospace hash ticking upward during a batch is a strong visual.
- **New `components/Dashboard/PolicyDecisionFeed.jsx`** — a stream of *why we didn't act*, with reason-code chips. This is the differentiator made visible; give it equal billing with the Kanban board.
- **`components/Dashboard/MetricRibbon.jsx`** — replace the single ROI figure with treated/control/incremental.
- **`App.jsx`** — fix the two broken drills: "Bank Outage" is a bare `alert()` (`App.jsx:270`), and "Fraud Alert" calls `api.optOut()`, writing `CUSTOMER_OPT_OUT` with `actor="customer"` (`App.jsx:274-286`) — a fraud quarantine recorded as a customer request is exactly the audit corruption this project claims to prevent. Add a real `POST /api/recovery/{id}/quarantine` writing `FRAUD_QUARANTINE` with `actor="system"`, and wire bank-outage to `fetch_payment_downtimes` (already imported and unused at `recovery_actions.py:37`) or remove the button.

---

## Workstream 7 — The reviewer-facing surface

**This workstream is not polish — for an AI-screened first round it carries as much weight as the code.**

**Rewrite `README.md`:**
- One-line thesis at the top, identical to the form and the video.
- **"Verify our claims yourself"** section — literal commands with expected output:
  ```
  make demo          # seeded batch; prints the exact numbers in this README
  make verify-ledger # walks the chain, prints head hash
  make tamper-demo   # corrupts one row, shows verification naming the broken link
  pytest tests/ -v   # N tests
  ```
- **An honest "Real vs. Simulated" table.** Counterintuitive but high-value: an explicit boundary preempts reviewer skepticism and reads as engineering maturity. Right now the README's biggest risk is that it overclaims — every unbacked claim is a defect an AI reviewer can find.
- Fix all doc drift: `/api/recovery/bank-outage`, `/api/recovery/fraud-alert`, `/api/batch/simulate` don't exist; `/api/webhook/razorpay` → `/api/webhooks/razorpay`; `/api/recovery/settle/{id}` → `/api/recovery/{id}/settle`. Add the missing `LICENSE` file the README links.
- Delete "cryptographic audit trail" as an adjective and replace it with the verification command.

**New: `Makefile`** — `demo`, `verify-ledger`, `tamper-demo`, `test`, `live-mode`.

**New: `results/`** — committed evidence from a real run: `run_report.md` (metrics + ledger head hash + guard-firing counts), `ledger_verification.txt`, `tamper_demo_output.txt`. A reviewer who won't clone the repo still sees the output.

**Update `docs/ARCHITECTURE.md`** to match the code, including the ledger and policy layers.

---

## Workstream 8 — Video + submission form

**Revise `demo_script.md`.** The existing narrative (*"when should the system stop?"*) is already the right pitch — the code just needs to make it true. Restructure the 5 minutes:

| Time | Beat |
|---|---|
| 0:00–0:45 | Problem + thesis: recovery without proof is just spam with a dashboard |
| 0:45–1:45 | Seeded batch run — stopping rules visibly firing in the policy feed |
| 1:45–2:45 | **Live ₹1 Razorpay test payment** → webhook → RECOVERED |
| 2:45–3:45 | **Tamper demo** — edit the DB, verification names the broken link |
| 3:45–4:30 | Incremental-lift number with the holdout explained |
| 4:30–5:00 | Consent registry across payments + close |

**Draft the four form fields** in `docs/SUBMISSION.md`:

- **Title:** RecoverOS — Provable Revenue Recovery
- **Objectives / What it solves:** lead with the compliance-and-proof gap, not the recovery rate. Every competitor will claim recovery; almost none will claim provability.
- **Build Challenges:** this field rewards genuine engineering narrative, and the honest ones here are unusually strong:
  1. **Chain integrity under concurrency** — a lock was the obvious answer and the wrong one; moving the invariant into a `UNIQUE` constraint on `prev_hash` made forks structurally impossible rather than merely unlikely.
  1b. **Getting the hash preimage right.** Two defects found before shipping: unprefixed field concatenation let content shift between adjacent fields without changing the hash, and money stored as `Float` put non-deterministic arithmetic into a value meant to be verifiable. Both fixed by one rule — hash only integers and length-prefixed bytes.
  2. **The guardrails never fired.** Instrumenting a batch showed zero halts — counters were checked once, before the first action, so they were always 0. Finding this required measuring our own system rather than trusting it.
  3. **Our demo batch was too small to support our own claim.** N=12 controls can't carry a causal lift estimate, which forced separating the watchable demo from the statistical measurement run.
  4. **Webhook idempotency** under Razorpay's retry behavior.

  Framing note: (2) and (3) are admissions of defect, and they are the strongest items in the list. A reviewer reads "we measured our own system and found it lying to us" as engineering maturity — and it directly reinforces the project's thesis.

---

## Sequencing (10 working days)

| Day | Work |
|---|---|
| 1 | W1 — **hash preimage encoding + golden fixture test first**, then ledger, schema-enforced chain invariant, SQLite pragmas, append-only enforcement. Also migrate cost to integer paise and timestamps to integer microseconds — both must land before any entry is written. |
| 2 | W1 — concurrency test, verify endpoints, CLI + tamper demo |
| 3 | W2 — consent model, suppression checks, quiet hours, inbound reply path, opt-out pattern fixes |
| 4 | W3 — `policy.py`, attempt ladder, guard rescoping, dataset expansion |
| 5 | W5 — outcome engine, contact-level stratified holdout, metrics decomposition, measurement run at scale |
| 6 | W4 — Razorpay live: fail-closed HMAC, idempotency, `payment.failed`, tunnel |
| 7 | W6 — frontend ledger panel, policy feed, metric ribbon, drill fixes |
| 8 | W7 — README rewrite, Makefile, `results/` artifacts, full test pass |
| 9 | W8 — record video (live payment take needs retries; budget the day) |
| 10 | W8 — submission form, final verification from a clean clone |

**If time compresses, cut in this order:** frontend polish → live Razorpay → quiet hours. **Never cut** the ledger, the policy decision records, or the README verification section — those are the thesis.

---

## Verification

Run from a clean clone before submitting:

1. `pip install -r backend/requirements.txt && pytest backend/tests/ -v` — all pass, count matches README.
2. `make demo` twice — **byte-identical metrics both times**. This is the fix for the reproducibility failure that motivated the whole plan.
3. `make verify-ledger` — chain valid, head hash printed, entry count matches the audit table.
4. `make tamper-demo` — verification fails and names the exact broken `sequence_no`.
5. Confirm the run output contains non-zero counts for each reason code: `RETRY_CAP_REACHED`, `CAC_CEILING`, `CONSENT_WITHDRAWN`, `QUIET_HOURS_DEFERRED`, `HARD_DECLINE`, `HOLDOUT_CONTROL`. **This is the check that the original build silently failed.**
6. Opt out on one payment, run the batch again, confirm a `SUPPRESSED_CONSENT` entry for a *different* payment sharing that phone.
7. Live mode: start the tunnel, trigger a recovery, pay ₹1 from a real UPI app, confirm the card reaches RECOVERED and the ledger entry carries the verified event ID. Re-POST the same webhook and confirm `{"status": "duplicate"}`.
8. Grep the README for every endpoint and `curl` each one.
9. Run the batch 5× consecutively and confirm no state poisoning — the run-4 collapse must not reproduce.
10. **Concurrency:** run the ledger under `uvicorn --workers 4` with concurrent batch triggers; chain must still verify with no sequence gaps. Then run the 4-writer stress test and confirm retries occurred and were absorbed.
11. **Webhook:** confirm startup fails when `RAZORPAY_WEBHOOK_SECRET == RAZORPAY_KEY_SECRET`. Replay a captured live webhook against the fixture test and confirm it verifies.
12. **Holdout integrity:** assert no `contact_hash` appears in both arms, and that per-class stratification holds. Re-run with the same seed and confirm identical arm assignment.
13. **Hash determinism:** golden-fixture preimage test passes byte-for-byte. `grep -rn "Float" backend/app/models.py` returns nothing for monetary columns. Compute the same chain on a second machine (or a different Python minor version) and confirm an identical head hash — this is the claim "independently verifiable" actually rests on.
