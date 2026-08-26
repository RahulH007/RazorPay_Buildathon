# Visible AI: Giving Gemini Real Work Without Losing the Audit

Date: 2026-08-25
Status: Approved for implementation planning

## Problem

Gemini is nearly absent from the running system. A measured demo batch produced
388 ledger entries, of which **4** carried an LLM model — all of them
`VOICE_SCRIPT_GENERATED`. All 57 records were classified by `rule_engine`; zero
by `llm_agent`.

Three causes, each independently sufficient:

1. `DEMO_MODE` defaults to `true` (`config.py:33`), and every function in
   `llm_agent.py` branches to a hand-written simulation in that mode.
2. Every `error_reason` in the dataset is already in `RULE_MAP`, so the slow
   path never triggers.
3. There is no inbound customer-reply path at all. `check_opt_out` in
   `guardrails.py:44` is dead code — `run_all_guards` is only ever called
   without a `message` argument — and `parse_customer_reply` is never called on
   an actual reply.

A defect found while designing this work, which changes the scope:

**`llm_classify` is wired to the wrong function.** `classifier.py:89` calls
`parse_customer_reply(record, record.error_description)`. That prompt is built
to interpret *customer replies*; it is being handed a *bank error string*. The
result is then mapped through `map_intent_to_class`, so an unrecognised error
code becomes `will_pay -> AUTH_FRICTION`, or far more often
`unclear -> HARD_DECLINE`. Today an unmapped error is silently killed by a
function that was never asked the right question.

## Goal

Gemini does three pieces of real work — diagnose unmapped failures, interpret
inbound customer replies, and write per-customer copy — while `policy.py`
retains every decision about whether to act, on what channel, and what to
spend.

Explicitly **out of scope**: letting the model recommend the action with a
policy veto. That option was considered and declined. The project's thesis is
that a reviewer can audit `policy.py` and cannot audit a prompt; moving spend
authority toward the model would trade the thesis for the appearance of agency.

## Constraints

- **Determinism must survive.** `make demo` currently reproduces byte-identical
  metrics and an identical chain head across runs. LLM output is
  non-deterministic; without a mitigation, putting it in a hashed ledger entry
  destroys the strongest verifiable claim in the repo.
- **`canonical()` must not change.** Altering the hash preimage means a
  `PREIMAGE_VERSION` bump and invalidates the golden fixture test
  (`7a0dd1df...`, length 268).
- **No API key required to reproduce.** The first review round is automated. A
  reviewer who cannot run the demo cannot verify anything.
- There is no migration tooling (no Alembic). Schema changes take effect by
  recreating the database.

## Approaches considered

**A. Record real responses, replay them deterministically (chosen).** Call
Gemini for real once, commit the responses, replay them in demo mode. Real
model output, tamper-evident in the ledger, reproducible without a key. Cost is
one committed fixture that must be refreshed when prompts or the dataset
change.

**B. Keep LLM output outside the hash chain.** Determinism is trivially
preserved, but the diagnosis — the most interesting artifact the model produces
— would sit outside the tamper-evidence everything else gets. A reviewer would
reasonably ask why the AI's reasoning is the one thing not covered.

**C. Accept non-determinism and drop the claim.** Simplest to build and the
most honest about what an LLM is, but it trades a proven, checkable claim for
convenience.

A is chosen because it is the only option where all three tasks do real work,
the output is auditable like everything else, and reproducibility holds.

## Design

### 1. `backend/app/llm_cache.py` — the determinism spine

Every Gemini call routes through one wrapper.

- Cache key: `sha256(model || prompt_version || canonical_json(inputs))`.
  `prompt_version` is an explicit integer per prompt, bumped when prompt text
  changes, so a prompt edit cannot silently reuse a stale response.
- Store: `backend/data/llm_cache.json`, committed. Each record holds the
  request inputs, the raw response text, `model`, `input_tokens`,
  `output_tokens`, `latency_ms`, and the UTC time it was recorded.
- `DEMO_MODE=true`: the key **must** hit the cache. A miss raises. It does not
  fall back to a simulation.
- `DEMO_MODE=false`: real call, response written back to the cache.
- `make refresh-llm-cache`: regenerates the file against live Gemini.

The cache-miss-raises rule is the load-bearing part. Today's silent fallback to
`_simulate_reply_parsing` is precisely why the README cannot currently claim
the model did anything. Failing loudly means a green demo run is evidence that
recorded model output was actually used.

`latency_ms` is replayed from the recorded call rather than re-measured, so the
value entering the hash preimage is stable across runs.

The committed cache is also the reviewer-facing evidence: real Gemini output,
readable without a key or a clone.

The existing `_simulate_*` helpers in `llm_agent.py` are removed. Their only
remaining role — a safe answer when the model is unavailable — is served by the
templates in the rejection path (section 4).

### 2. Task 2 — real diagnosis in `classifier.py`

**Fast path** unchanged: `error_reason in RULE_MAP` gives a deterministic class
with `actor="rule_engine"` and zero LLM cost. This remains the path for the
majority of records, and that is the point — the model is used where rules run
out, not everywhere.

**Slow path** calls a new `llm_agent.diagnose_failure(record) -> FailureDiagnosis`,
replacing the `parse_customer_reply` misuse entirely. Structured JSON:

```json
{
  "root_cause_class": "MANDATE_BALANCE",
  "technical_explanation": "The e-mandate debit was presented but the account had insufficient balance at presentation time.",
  "suggested_action": "Re-present after the customer's typical salary credit date.",
  "confidence": 0.86
}
```

- `root_cause_class` is validated against the five-member `FailureClass` enum.
  A value outside it is treated as a low-confidence result and escalated, not
  raised as an error.
- `confidence < CONFIDENCE_THRESHOLD` (0.7) writes `ESCALATED_TO_HUMAN`, as the
  current code does.
- `suggested_action` is **recorded and never executed.** `policy.py` reads
  `root_cause_class` and nothing else from this object. The suggestion exists
  so a reviewer can see the model's reasoning and compare it against what the
  policy actually did.

`map_intent_to_class` is **deleted.** It exists only to serve the miswiring
described in the Problem section: it converts reply intents into failure
classes, which is meaningful nowhere. The inbound path (section 3) dispatches
on intent directly, and the slow path now returns a class of its own.

**Dataset:** `backend/data/test_batch_50.json` gains 8 records whose
`error_reason` is outside `RULE_MAP` and whose `error_description` is free text
— at least two per non-terminal failure class, so the slow path is exercised
across the ladder rather than concentrated in one column of the board.

### 3. Task 1 — the inbound reply path

New endpoint: `POST /api/recovery/{payment_id}/reply`, body `{"message": "..."}`.

Pipeline: `sanitize_input` -> `parse_customer_reply` (through the cache) ->
ledger entry `CUSTOMER_REPLY_PARSED` carrying intent, sentiment, confidence and
LLM metadata -> deterministic dispatch:

| intent | consequence |
| --- | --- |
| `opt_out` | `consent.record_opt_out(source="whatsapp_reply")` — suppression crosses payments for that contact |
| `request_delay` with a date | `promise_to_pay_at` set on the record; policy defers the next attempt past it |
| `dispute` | `queue_for_human()` |
| `will_pay` | `promise_to_pay_at` set to 24h out — same mechanism as an explicit date, not a second one |
| `unclear`, or confidence below threshold | `ESCALATED_TO_HUMAN` |

**The regex safety net.** `check_opt_out` runs alongside Gemini and its result
is OR-ed with the model's. The LLM can only *add* suppression, never remove it:
if Gemini returns `will_pay` but the regex matches "band karo", the contact is
suppressed. This revives the dead code as a fail-safe rather than a redundancy,
and it states the safety posture in one auditable line — the model is never the
only thing standing between a customer and another message.

**Schema change:** `PaymentFailureRecord` gains
`promise_to_pay_at` (`DateTime`, nullable). `policy.decide_next_action` gains a
check between the holdout check and the attempt cap: if `promise_to_pay_at` is
in the future, return a deferral with a new reason code
`PROMISE_TO_PAY_PENDING`. A deferral, like quiet hours, leaves the record in
`INTERVENING` rather than stopping it.

**Dataset:** records gain an optional `customer_reply` field. The batch
simulator delivers a record's reply immediately after that record's first
outbound attempt — replies are answers to messages, so delivering one before an
attempt would be incoherent, and delivering it later would leave the path
unexercised for single-attempt ladders. This makes the path visible in the demo
run rather than reachable only by curl.

### 4. Task 3 — per-customer copy

`generate_hinglish_script` is joined by a WhatsApp-message sibling; both route
through the cache. Two guards on the output:

1. The existing `BANNED_PHRASES` check.
2. A new assertion that every amount and payment link appearing in the
   generated text matches the record exactly.

On either failure the message is rejected, the deterministic template is sent
instead, and a `LLM_OUTPUT_REJECTED` ledger entry records what was rejected and
why. **Gemini writes the words; it never writes the numbers.**

### 5. Ledger: nothing new enters the preimage

`canonical()` is not touched.

- The diagnosis JSON and the parsed-reply result go into `details`, which is
  already inside the preimage.
- `llm_model`, `llm_input_tokens`, `llm_output_tokens`, `llm_latency_ms` and
  `llm_confidence_bp` are already preimage fields.

So the model's output is tamper-evident with no `PREIMAGE_VERSION` bump and no
invalidated golden fixture.

New actions: `FAILURE_DIAGNOSED_LLM`, `CUSTOMER_REPLY_PARSED`,
`LLM_OUTPUT_REJECTED`, `PROMISE_TO_PAY_RECORDED`.

**Expected churn:** more entries means a new entry count and a new chain head.
The published head `1c61537b...` in `README.md` and under `results/` must be
regenerated once implementation settles. This is a refresh chore, not a broken
claim — what matters is that the head is identical across repeated runs, and
that property is preserved.

### 6. Visibility

LLM metadata currently renders in exactly one place: the Audit Inspector modal
(`AuditEntry.jsx:107`), reachable only by clicking a card. Three additions:

- `GET /api/llm/activity` — calls made, models used, token totals, latency
  distribution, cache hit/miss counts, rejections, and the rule-engine versus
  llm-agent split across the batch.
- An **AI Activity** strip on the dashboard driven by that endpoint, giving the
  model's work equal billing with the Kanban board.
- `run_demo` prints an LLM summary block, so the terminal capture in the pitch
  video shows the same numbers.

### 7. Testing

New and modified tests:

- Cache hit returns the recorded response; cache miss under `DEMO_MODE=true`
  raises rather than falling back.
- A `prompt_version` bump invalidates the cached key.
- Slow-path JSON validated against the enum; an out-of-enum
  `root_cause_class` escalates instead of raising.
- Sub-threshold confidence writes `ESCALATED_TO_HUMAN`.
- Regex opt-out overrides a `will_pay` verdict from the model.
- An amount mismatch in generated copy triggers `LLM_OUTPUT_REJECTED` and falls
  back to the template.
- `promise_to_pay_at` in the future produces `PROMISE_TO_PAY_PENDING` and no
  attempt.
- Two consecutive demo runs produce an identical chain head.
- The existing golden preimage test must still pass unchanged.

## Files

New: `backend/app/llm_cache.py`, `backend/data/llm_cache.json`,
`backend/app/routes/llm.py`, `frontend/src/components/Dashboard/AiActivityStrip.jsx`,
`backend/tests/test_llm_cache.py`, `backend/tests/test_diagnosis.py`,
`backend/tests/test_inbound_reply.py`.

Modified: `classifier.py`, `llm_agent.py`, `policy.py`, `models.py`,
`guardrails.py`, `recovery_actions.py`, `recovery_simulator.py`,
`routes/recovery.py`, `config.py`, `data/test_batch_50.json`, `Makefile`,
`README.md`, `results/`.

## Success criteria

1. A demo batch shows a non-trivial number of records diagnosed by
   `llm_agent`, with the fast path still handling the mapped majority.
2. At least one seeded reply produces cross-payment suppression via the LLM
   path, proven by a ledger entry.
3. `make demo` run twice yields an identical chain head.
4. A reviewer can read real Gemini output in `llm_cache.json` without an API
   key.
5. `LLM_OUTPUT_REJECTED` fires at least once in the demo, proving the guard is
   live rather than decorative.
6. Every claim about the model in the README is backed by a command a reviewer
   can run.

## Cache refresh semantics

`make refresh-llm-cache` fills only missing keys by default, so a dataset
addition costs a handful of calls rather than a full re-record — and, more
importantly, so existing recorded responses stay byte-stable and the chain head
does not move for unrelated reasons. `make refresh-llm-cache ARGS=--all`
re-records everything; that is the deliberate act that follows a prompt
rewrite, and it is expected to change the published head.
