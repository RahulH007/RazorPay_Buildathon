# RecoverOS — AI Agent Implementation Plan

> A fully agent-executable plan for building RecoverOS end-to-end. Every phase is self-contained with exact file paths, commands, dependencies, code structure, and verification steps so the AI agent can execute without ambiguity.

---

## Proposed Changes

### Project Structure (Final)

```
e:\Razorpay\
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app entry, CORS, WebSocket, route mounting
│   │   ├── config.py                  # Env vars, Razorpay keys, Gemini keys, constants
│   │   ├── database.py                # SQLAlchemy engine, session, Base
│   │   ├── models.py                  # ORM: PaymentFailureRecord, AuditTrailEntry
│   │   ├── schemas.py                 # Pydantic: request/response models, JSON schemas
│   │   ├── state_machine.py           # FSM: INGESTED→DIAGNOSED→INTERVENING→RECOVERED/FAILED_STOPPED
│   │   ├── classifier.py              # Rule Engine (Fast Path) + LLM router
│   │   ├── llm_agent.py              # Gemini integration: reply parser, script generator, P2P extractor
│   │   ├── guardrails.py             # Opt-out listener, CAC ceiling, retry caps, fraud halt
│   │   ├── recovery_actions.py        # Action orchestrator: retry, WhatsApp link, voice, P2P
│   │   ├── recovery_simulator.py      # Probabilistic batch simulation engine
│   │   ├── webhook_handler.py         # Razorpay webhook ingestion + signature verification
│   │   ├── settlement.py              # Settlement verification loop + timeout handler
│   │   ├── voice_pipeline.py          # Hinglish script generation + TTS (Sarvam AI) integration
│   │   ├── websocket_manager.py       # WebSocket connection manager for live dashboard
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── webhooks.py            # POST /api/webhooks/razorpay
│   │       ├── batch.py               # POST /api/batch/run, GET /api/batch/{id}/status
│   │       ├── recovery.py            # GET /api/recovery/{id}, POST /api/recovery/{id}/opt-out
│   │       ├── metrics.py             # GET /api/metrics/dashboard
│   │       └── audit.py               # GET /api/audit/{payment_id}
│   ├── data/
│   │   └── test_batch_50.json         # 50-record synthetic dataset
│   ├── tests/
│   │   ├── test_classifier.py
│   │   ├── test_guardrails.py
│   │   ├── test_state_machine.py
│   │   └── test_batch_simulation.py
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── App.jsx                    # Root app with layout
│   │   ├── App.css                    # Global styles + dark theme
│   │   ├── index.js                   # React entry
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js        # WebSocket hook for real-time updates
│   │   │   └── useBatchSimulation.js  # Batch trigger + polling hook
│   │   ├── components/
│   │   │   ├── Dashboard/
│   │   │   │   ├── MetricRibbon.jsx   # GMV, Recovery Rate, ROI, Cost cards
│   │   │   │   ├── KanbanBoard.jsx    # 5-column pipeline board
│   │   │   │   ├── KanbanCard.jsx     # Individual recovery record card
│   │   │   │   └── BatchControls.jsx  # "Run Batch" button + progress bar
│   │   │   ├── PhoneSimulator/
│   │   │   │   ├── PhoneFrame.jsx     # iPhone-style frame shell
│   │   │   │   ├── WhatsAppScreen.jsx # WhatsApp chat with payment link
│   │   │   │   ├── VoiceCallScreen.jsx # Incoming call UI + DTMF buttons
│   │   │   │   └── UPIPayScreen.jsx   # UPI payment authorization mock
│   │   │   ├── AuditInspector/
│   │   │   │   ├── AuditModal.jsx     # Modal overlay with timeline
│   │   │   │   └── AuditEntry.jsx     # Single audit log row
│   │   │   └── EdgeCasePanel/
│   │   │       └── EdgeCaseToggles.jsx # Opt-out, bank outage, fraud toggles
│   │   └── utils/
│   │       ├── api.js                 # Axios/fetch wrappers for backend
│   │       └── formatters.js          # Currency, date, percentage formatters
│   ├── package.json
│   └── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   └── API.md
├── Problem_Statement.md
├── recoveros_blueprint.md
└── README.md
```

---

## Phase 1 — Project Scaffolding & Data Layer

> **Goal:** Runnable backend skeleton with database, schemas, synthetic dataset, and health-check endpoint.

### Step 1.1: Initialize Backend

```bash
# From e:\Razorpay
mkdir backend && cd backend
python -m venv venv
venv\Scripts\activate
```

#### [NEW] `backend/requirements.txt`
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.32
pydantic==2.8.0
razorpay==1.4.2
google-genai==1.5.0
python-dotenv==1.0.1
httpx==0.27.0
websockets==12.0
pytest==8.3.0
pytest-asyncio==0.23.0
```

```bash
pip install -r requirements.txt
```

#### [NEW] `backend/.env.example`
```
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXX
RAZORPAY_WEBHOOK_SECRET=XXXXXXXXXXXXXXXXXXXXXX
GEMINI_API_KEY=XXXXXXXXXXXXXXXXXXXXXX
DATABASE_URL=sqlite:///./recoveros.db
SARVAM_API_KEY=XXXXXXXXXXXXXXXXXXXXXX
```

#### [NEW] `backend/app/config.py`
- Load all env vars via `python-dotenv`
- Export constants: `MAX_RETRIES=3`, `CAC_CEILING_PERCENT=15`, `SETTLEMENT_TIMEOUT_MINUTES=30`, `CONFIDENCE_THRESHOLD=0.7`
- Export `RECOVERY_RATES` and `CHANNEL_COSTS` dicts from blueprint §7

#### [NEW] `backend/app/database.py`
- SQLAlchemy `create_engine` with SQLite URL from config
- `SessionLocal` factory, `Base` declarative base
- `get_db()` dependency for FastAPI

#### [NEW] `backend/app/models.py`
ORM models matching the blueprint §11 JSON schema:

| Model | Key Columns |
|:---|:---|
| `PaymentFailureRecord` | `payment_id` (PK), `amount`, `currency`, `method`, `subscription_id`, `invoice_id`, `merchant_id`, `customer_name`, `customer_email`, `customer_phone`, `error_source`, `error_step`, `error_reason`, `error_description`, `failure_class` (enum), `recovery_state` (enum), `recovery_channel`, `created_at`, `updated_at` |
| `AuditTrailEntry` | `id` (PK, auto), `payment_id` (FK), `timestamp`, `action`, `actor` (enum), `details`, `cost_incurred_inr`, `llm_model`, `llm_input_tokens`, `llm_output_tokens`, `llm_latency_ms`, `llm_confidence` |
| `BatchRun` | `batch_id` (PK), `status`, `total_records`, `processed_records`, `recovered_gmv`, `total_gmv`, `channel_cost`, `started_at`, `completed_at` |

#### [NEW] `backend/app/schemas.py`
- Pydantic models: `PaymentFailureCreate`, `PaymentFailureResponse`, `AuditEntryResponse`, `BatchRunResponse`, `DashboardMetrics`, `WebhookPayload`
- Enums: `FailureClass`, `RecoveryState`, `RecoveryChannel`, `ActorType`

### Step 1.2: Synthetic Dataset

#### [NEW] `backend/data/test_batch_50.json`
Generate a 50-record JSON array. Each record follows the `PaymentFailureRecord` schema. Distribution:

| Class | Count | Amount Range (paise) | Error Codes to Use |
|:---|:---|:---|:---|
| Transient Technical | 15 | 200000–800000 | `bank_technical_error`, `gateway_error` |
| Auth / Friction | 10 | 100000–500000 | `authentication_failed`, `incorrect_otp` |
| Mandate / Balance | 15 | 150000–600000 | `mandate_insufficient_funds`, `card_expired` |
| B2B Receivables | 6 | 500000–1500000 | `invoice_overdue_15d` |
| Hard Decline | 4 | 100000–300000 | `compliance_violation`, `debit_instrument_blocked` |

- Use realistic Indian names, `+91` phone numbers, `@example.com` emails
- All records start at `recovery_state: "INGESTED"`, empty `audit_trail`
- Payment methods distributed: `upi`, `card`, `emandate`, `netbanking`
- B2B records include `invoice_id`, mandate records include `subscription_id`

### Step 1.3: Main App & Health Check

#### [NEW] `backend/app/main.py`
- Create FastAPI app with title "RecoverOS API"
- CORS middleware (allow `http://localhost:3000`)
- On startup: `Base.metadata.create_all(engine)` to auto-create tables
- Mount route modules from `app.routes.*`
- `GET /health` → `{"status": "ok", "version": "1.0.0"}`

### ✅ Phase 1 Verification
```bash
cd backend
uvicorn app.main:app --reload --port 8000
# Verify: GET http://localhost:8000/health → 200
# Verify: SQLite DB file created at ./recoveros.db
# Verify: test_batch_50.json has exactly 50 records with correct class distribution
```

---

## Phase 2 — State Machine & Classifier

> **Goal:** Working FSM with rule-based classification and audit trail logging.

### Step 2.1: State Machine

#### [NEW] `backend/app/state_machine.py`
- Use `transitions` library
- States: `INGESTED`, `DIAGNOSED`, `INTERVENING`, `RECOVERED`, `FAILED_STOPPED`
- Transitions:

```
INGESTED    → DIAGNOSED       (trigger: classify)
DIAGNOSED   → INTERVENING     (trigger: start_recovery)
DIAGNOSED   → FAILED_STOPPED  (trigger: hard_decline)
INTERVENING → RECOVERED       (trigger: payment_captured)
INTERVENING → FAILED_STOPPED  (trigger: timeout / opt_out / max_retries)
```

- On every transition: auto-write `AuditTrailEntry` with timestamp, action, actor, details
- Emit WebSocket event: `{"type": "state_change", "payment_id": "...", "from": "...", "to": "..."}`

### Step 2.2: Rule Engine Classifier

#### [NEW] `backend/app/classifier.py`

```python
# Decision boundary from blueprint §3
RULE_MAP = {
    "bank_technical_error": FailureClass.TRANSIENT_TECHNICAL,
    "gateway_error": FailureClass.TRANSIENT_TECHNICAL,
    "authentication_failed": FailureClass.AUTH_FRICTION,
    "incorrect_otp": FailureClass.AUTH_FRICTION,
    "mandate_insufficient_funds": FailureClass.MANDATE_BALANCE,
    "card_expired": FailureClass.MANDATE_BALANCE,
    "invoice_overdue_15d": FailureClass.B2B_RECEIVABLE,
    "compliance_violation": FailureClass.HARD_DECLINE,
    "debit_instrument_blocked": FailureClass.HARD_DECLINE,
}

def classify(record: PaymentFailureRecord) -> FailureClass:
    """Fast Path: deterministic rule lookup."""
    error_reason = record.error_reason
    if error_reason in RULE_MAP:
        return RULE_MAP[error_reason]
    # Slow Path: send to LLM for ambiguous cases
    return llm_classify(record)
```

- After classification: transition state `INGESTED → DIAGNOSED`
- Log audit entry: `"CLASSIFIED_{failure_class}"` with actor `rule_engine` or `llm_agent`
- For `HARD_DECLINE`: immediately transition to `FAILED_STOPPED` with "why we didn't act" detail

### Step 2.3: Guardrails Engine

#### [NEW] `backend/app/guardrails.py`

| Guard | Logic |
|:---|:---|
| `check_opt_out(message)` | Scan for `STOP`, `CANCEL`, `NO`, `mat karo`, `band karo` (case-insensitive, Hindi-aware). Return `True` if match. |
| `check_retry_cap(record)` | Count `AuditTrailEntry` where `action LIKE 'RETRY%'` for this `payment_id`. Return `True` if count ≥ `MAX_RETRIES`. |
| `check_cac_ceiling(record)` | Sum `cost_incurred_inr` from audit trail. Return `True` if sum ≥ `record.amount * CAC_CEILING_PERCENT / 100`. |
| `check_fraud_flag(record)` | Return `True` if `failure_class == HARD_DECLINE`. |
| `run_all_guards(record, message=None)` | Run all checks. Return `(allowed: bool, halt_reason: str | None)`. |

### ✅ Phase 2 Verification
```bash
cd backend
python -m pytest tests/test_classifier.py tests/test_guardrails.py tests/test_state_machine.py -v
```
- Test: all 50 records from `test_batch_50.json` classify correctly to expected class
- Test: Hard Decline records skip straight to `FAILED_STOPPED`
- Test: opt-out detection catches "STOP", "mat karo", "CANCEL"
- Test: retry cap triggers after 3 attempts
- Test: CAC ceiling triggers when cost exceeds 15% of amount

---

## Phase 3 — LLM Agent Integration

> **Goal:** Gemini-powered customer reply parsing, B2B negotiation, and Hinglish script generation.

### Step 3.1: LLM Agent Core

#### [NEW] `backend/app/llm_agent.py`

Three LLM functions, all using `google-genai` SDK:

**Function 1: `parse_customer_reply(record, reply_text) → ParsedIntent`**
- Model: `gemini-2.0-flash`
- Prompt: exact template from blueprint §3 (Customer Reply Parsing)
- Use `response_schema` parameter for structured JSON output
- Sanitize `reply_text`: strip HTML, limit to 500 chars, escape injection patterns
- If `confidence < 0.7`: set `requires_human = True`
- Log audit entry with `llm_metadata` (model, tokens, latency, confidence)

**Function 2: `generate_hinglish_script(record) → str`**
- Model: `gemini-2.5-pro`
- Prompt: exact template from blueprint §6 (Voice Script Generation)
- Validate output against banned-phrases list
- Return plain-text Hinglish script

**Function 3: `extract_p2p_date(record, reply_text) → date | None`**
- Model: `gemini-2.0-flash`
- Extract promise-to-pay date from natural language ("next Friday", "salary aane do", "1st ko kar dunga")
- Return ISO date or `None`

### Step 3.2: Confidence Router

Add to `classifier.py`:

```python
async def llm_classify(record):
    """Slow Path: use LLM for ambiguous failure reasons."""
    result = await parse_customer_reply(record, record.error_description)
    if result.confidence < CONFIDENCE_THRESHOLD:
        # Escalate to human review
        record.recovery_state = "FAILED_STOPPED"
        log_audit(record, "ESCALATED_TO_HUMAN", actor="llm_agent",
                  details=f"Confidence {result.confidence:.2f} below threshold")
        return FailureClass.HARD_DECLINE  # treated as non-actionable
    return map_intent_to_class(result.intent)
```

### ✅ Phase 3 Verification
- Test: `parse_customer_reply` returns valid JSON matching schema for 5 sample replies (Hinglish, English, opt-out, delay request, dispute)
- Test: confidence < 0.7 routes to human escalation
- Test: `generate_hinglish_script` output contains customer name, amount, DTMF instructions
- Test: `extract_p2p_date` correctly parses "1st September", "next Monday", "salary ke baad"
- Mock Gemini calls in tests using `unittest.mock.patch`

---

## Phase 4 — Recovery Action Orchestrator

> **Goal:** Channel-specific recovery actions that generate real Razorpay payment links and update state.

### Step 4.1: Action Orchestrator

#### [NEW] `backend/app/recovery_actions.py`

| Action | Implementation |
|:---|:---|
| `silent_retry(record)` | Check Razorpay Downtime API (`GET /v1/payments/downtimes`). If resolved → create new payment attempt via Razorpay API. Log retry count. Max 3 retries over 4 hours. |
| `send_whatsapp_link(record)` | Generate Razorpay Payment Link (`POST /v1/payment_links`) with `amount`, `customer.phone`, 15-min expiry. Return link URL. Log cost ₹0.50. |
| `resequence_mandate(record)` | Calculate next salary-cycle date (1st or 5th of next month). Schedule retry. Send 1-click mandate update link. Log cost ₹0.50. |
| `initiate_voice_recovery(record)` | Call `generate_hinglish_script()` → call Sarvam AI TTS API → store audio URL. In demo mode: return audio URL for phone simulator playback. Log cost ₹2.00. |
| `log_hard_decline(record)` | No customer outreach. Write "why we didn't act" audit entry. Transition to `FAILED_STOPPED`. |

**Dispatch logic:**
```python
ACTION_MAP = {
    FailureClass.TRANSIENT_TECHNICAL: silent_retry,
    FailureClass.AUTH_FRICTION: send_whatsapp_link,
    FailureClass.MANDATE_BALANCE: resequence_mandate,
    FailureClass.B2B_RECEIVABLE: initiate_voice_recovery,
    FailureClass.HARD_DECLINE: log_hard_decline,
}

async def execute_recovery(record):
    guards_ok, halt_reason = run_all_guards(record)
    if not guards_ok:
        transition(record, "FAILED_STOPPED", reason=halt_reason)
        return
    
    action = ACTION_MAP[record.failure_class]
    transition(record, "INTERVENING")
    result = await action(record)
    log_audit(record, f"ACTION_{action.__name__}", details=result)
```

### Step 4.2: Voice Pipeline

#### [NEW] `backend/app/voice_pipeline.py`

```python
async def generate_voice_audio(record) -> str:
    """Full pipeline: LLM script → Sarvam TTS → audio URL."""
    # 1. Generate Hinglish script via Gemini
    script = await generate_hinglish_script(record)
    
    # 2. Validate script against banned phrases
    validate_script(script, BANNED_PHRASES)
    
    # 3. Synthesize via Sarvam AI TTS (or mock in demo)
    if DEMO_MODE:
        audio_url = mock_tts(script)  # Save to local file, return URL
    else:
        audio_url = await sarvam_tts(script, voice="saaras", lang="hi-IN")
    
    # 4. Log audit trail
    log_audit(record, "VOICE_SCRIPT_GENERATED", details=script[:200])
    
    return audio_url
```

### Step 4.3: Settlement Verification

#### [NEW] `backend/app/settlement.py`
- On `payment.captured` webhook: match `payment_id` → transition state to `RECOVERED` → update batch metrics → emit WebSocket event
- On `invoice.paid` webhook: same flow for B2B records
- Background task: check all `INTERVENING` records older than 30 min → transition to `FAILED_STOPPED` with reason `settlement_timeout`

### ✅ Phase 4 Verification
```bash
cd backend
python -m pytest tests/test_batch_simulation.py -v
```
- Test: `POST /api/batch/run` processes all 50 records
- Test: each failure class dispatches to correct action
- Test: Hard Decline records get "why we didn't act" audit entries
- Test: guardrails block actions when limits are exceeded
- Test: settlement timeout fires for unresolved records

---

## Phase 5 — API Routes & Batch Simulation

> **Goal:** All REST endpoints live and testable via curl/Postman.

### Step 5.1: Route Implementations

#### [NEW] `backend/app/routes/webhooks.py`
- `POST /api/webhooks/razorpay` — Verify HMAC-SHA256 signature → parse webhook type → dispatch to ingestion or settlement handler

#### [NEW] `backend/app/routes/batch.py`
- `POST /api/batch/run` — Load `test_batch_50.json` → classify all → execute recovery actions with probabilistic outcomes → return `batch_id`
- `GET /api/batch/{batch_id}/status` — Return live metrics: processed count, recovered GMV, per-class breakdown

#### [NEW] `backend/app/routes/recovery.py`
- `GET /api/recovery/{payment_id}` — Full record with audit trail
- `POST /api/recovery/{payment_id}/opt-out` — Trigger opt-out guardrail → halt → audit log

#### [NEW] `backend/app/routes/metrics.py`
- `GET /api/metrics/dashboard` — Aggregate: total GMV, recovered GMV, recovery rate, channel cost, net ROI, cost per recovery, per-class breakdown

#### [NEW] `backend/app/routes/audit.py`
- `GET /api/audit/{payment_id}` — Ordered audit trail entries with LLM metadata

### Step 5.2: Batch Simulation Engine

#### [NEW] `backend/app/recovery_simulator.py`
- Implements the pseudocode from blueprint §7
- Uses `RECOVERY_RATES` and `CHANNEL_COSTS` from config
- `random.random()` determines per-record recovery outcome
- Processes records with realistic delays (100-500ms staggered) to create a streaming effect on the dashboard
- Emits WebSocket events after each record for real-time Kanban updates

### Step 5.3: WebSocket Manager

#### [NEW] `backend/app/websocket_manager.py`
- `ConnectionManager` class with `connect()`, `disconnect()`, `broadcast()`
- Event types: `state_change`, `metric_update`, `batch_progress`, `record_ingested`, `record_recovered`
- JSON payload format: `{"type": "...", "data": {...}, "timestamp": "..."}`

### ✅ Phase 5 Verification
```bash
# Start server
uvicorn app.main:app --reload --port 8000

# Test batch run
curl -X POST http://localhost:8000/api/batch/run
# → Returns batch_id, starts processing

# Test batch status
curl http://localhost:8000/api/batch/{batch_id}/status
# → Returns live metrics

# Test individual record
curl http://localhost:8000/api/recovery/pay_O7d8K2j9Kl1
# → Returns record with audit trail

# Test dashboard metrics
curl http://localhost:8000/api/metrics/dashboard
# → Returns aggregated metrics

# Test opt-out
curl -X POST http://localhost:8000/api/recovery/pay_O7d8K2j9Kl1/opt-out
# → Returns halted record with audit entry
```

---

## Phase 6 — React Frontend: Dashboard

> **Goal:** Dark-mode FinOps dashboard with metric ribbon, Kanban board, and batch controls.

### Step 6.1: Initialize Frontend

```bash
cd e:\Razorpay
npx -y create-vite@latest frontend -- --template react
cd frontend
npm install
npm install axios
```

### Step 6.2: Global Styles & Theme

#### [NEW] `frontend/src/App.css`
- Dark mode: `background: #0a0a0f`, card backgrounds `#12121a`, accent gradients (emerald → teal)
- Typography: Google Fonts `Inter` (body) + `JetBrains Mono` (numbers/metrics)
- Glassmorphism cards: `backdrop-filter: blur(12px)`, subtle borders `rgba(255,255,255,0.06)`
- Micro-animations: fade-in for cards, pulse for live metrics, slide-in for Kanban columns
- Responsive grid: dashboard collapses gracefully on smaller viewports

### Step 6.3: Metric Ribbon

#### [NEW] `frontend/src/components/Dashboard/MetricRibbon.jsx`
- 6 metric cards in a horizontal strip:
  1. **Total Ingested GMV** (₹ formatted)
  2. **Recovered GMV** (₹ formatted, animated counter)
  3. **Recovery Rate** (% with circular progress)
  4. **Net ROI** (₹ formatted)
  5. **Channel Cost** (₹ formatted)
  6. **Cost per Recovery** (₹ formatted)
- Values update in real-time via WebSocket
- Animated count-up effect when metrics change

### Step 6.4: Kanban Board

#### [NEW] `frontend/src/components/Dashboard/KanbanBoard.jsx`
- 5 columns: `Ingested` → `Diagnosed` → `Active Intervention` → `Settled (Won)` → `Gracefully Aborted`
- Each column shows count badge
- Column backgrounds use subtle gradient tints per state
- Cards animate from column to column on state transitions

#### [NEW] `frontend/src/components/Dashboard/KanbanCard.jsx`
- Shows: payment_id (truncated), amount (₹), failure class badge (color-coded), recovery channel icon, customer name
- Click → opens Audit Inspector modal
- Failure class colors: Transient=blue, Auth=amber, Mandate=purple, B2B=teal, Hard=red

### Step 6.5: Batch Controls

#### [NEW] `frontend/src/components/Dashboard/BatchControls.jsx`
- Large "▶ Run 50-Record Batch" button with glow effect
- Progress bar showing `processed / total` records
- Timer showing elapsed time
- "Processing..." state with shimmer animation
- Edge case toggle buttons: "Trigger Opt-Out", "Simulate Bank Outage", "Trigger Fraud Alert"

### Step 6.6: WebSocket Hook

#### [NEW] `frontend/src/hooks/useWebSocket.js`
- Connects to `ws://localhost:8000/ws/dashboard`
- Auto-reconnect with exponential backoff
- Dispatches events to update Kanban cards and metric ribbon
- Returns `{ isConnected, lastEvent, metrics, records }`

### ✅ Phase 6 Verification
```bash
cd frontend
npm run dev
# Open http://localhost:5173
# Verify: dark-mode dashboard renders
# Verify: "Run Batch" button triggers POST /api/batch/run
# Verify: Kanban cards stream across columns in real-time
# Verify: metric ribbon updates as records are processed
```

---

## Phase 7 — Phone Simulator

> **Goal:** Interactive smartphone UI showing WhatsApp recovery messages, voice call simulation, and UPI payment flow.

### Step 7.1: Phone Frame

#### [NEW] `frontend/src/components/PhoneSimulator/PhoneFrame.jsx`
- iPhone-style frame: rounded corners, notch, status bar (time, battery, signal)
- Dark bezel with inner screen area
- Tab switcher at bottom: WhatsApp | Voice Call | UPI Pay
- Screen content switches based on selected recovery record and channel

### Step 7.2: WhatsApp Screen

#### [NEW] `frontend/src/components/PhoneSimulator/WhatsAppScreen.jsx`
- WhatsApp-style chat interface: green header, chat bubbles, timestamp
- Recovery message bubble with:
  - Merchant name + logo
  - Personalized message: "Hi {name}, your payment of ₹{amount} for {description} couldn't be processed."
  - **"Pay ₹{amount} →"** button (styled as WhatsApp action button)
- Clicking the pay button → navigates to UPI Pay screen

### Step 7.3: Voice Call Screen

#### [NEW] `frontend/src/components/PhoneSimulator/VoiceCallScreen.jsx`
- Incoming call UI: caller name "{merchant_name}", "RecoverOS" subtitle
- Accept / Decline buttons
- On accept: plays Hinglish TTS audio (fetched from backend `/api/voice/{payment_id}`)
- DTMF button grid: 1 (Pay Now) | 2 (Delay) | 9 (Stop)
- Button press sends action to backend → state updates → dashboard reflects change

### Step 7.4: UPI Pay Screen

#### [NEW] `frontend/src/components/PhoneSimulator/UPIPayScreen.jsx`
- Razorpay-styled payment page showing amount, merchant name
- "Authorize UPI" button
- On click: calls backend to trigger Razorpay test payment capture
- Success animation: ✓ checkmark with confetti
- After success: Kanban card moves to "Settled (Won)", GMV counter increments

### ✅ Phase 7 Verification
```bash
# With both backend and frontend running:
# 1. Run a batch
# 2. Click a WhatsApp-channel card in Kanban → phone shows WhatsApp screen
# 3. Click "Pay" → phone shows UPI screen → click "Authorize" → card moves to "Settled"
# 4. Click a Voice-channel card → phone shows incoming call → Accept → audio plays → press DTMF
# 5. Verify dashboard metrics update after each interaction
```

---

## Phase 8 — Audit Inspector & Edge Cases

> **Goal:** Full transparency modal and demo-ready edge case toggles.

### Step 8.1: Audit Inspector Modal

#### [NEW] `frontend/src/components/AuditInspector/AuditModal.jsx`
- Triggered by clicking any Kanban card
- Full-screen overlay with timeline view
- Each entry shows: timestamp, action badge, actor (rule_engine / llm_agent / system / customer), details
- LLM entries expand to show: model, tokens, latency, confidence score
- "Why we didn't act" entries highlighted in red for Hard Decline records
- Cost column showing cumulative spend per record
- Close button returns to dashboard

### Step 8.2: Edge Case Toggles

#### [NEW] `frontend/src/components/EdgeCasePanel/EdgeCaseToggles.jsx`
Three demo buttons integrated into `BatchControls`:

| Toggle | Backend Behavior | Dashboard Effect |
|:---|:---|:---|
| **"Trigger Customer Opt-Out"** | Sends opt-out message for a random `INTERVENING` record | Card jumps to "Gracefully Aborted" with audit entry |
| **"Simulate Bank Outage"** | Sets downtime flag for all `TRANSIENT_TECHNICAL` records | Silent retries pause, cards show "Waiting for bank" status |
| **"Trigger Fraud Alert"** | Flags a random record as `compliance_violation` | Card jumps to "Gracefully Aborted" with "zero retries" audit |

### ✅ Phase 8 Verification
- Click Kanban card → Audit modal opens with full timeline
- Hard Decline card → audit shows "WHY_WE_DIDNT_ACT" entry
- Click "Trigger Opt-Out" → a card transitions to aborted with audit
- Click "Simulate Bank Outage" → transient cards show waiting state
- Click "Trigger Fraud Alert" → a card transitions with zero-retry audit

---

## Phase 9 — Integration Testing & Polish

> **Goal:** End-to-end flow works, edge cases handled, UI polished.

### Step 9.1: End-to-End Test Script

#### [NEW] `backend/tests/test_e2e.py`
```python
# Automated E2E test:
# 1. POST /api/batch/run → get batch_id
# 2. Poll GET /api/batch/{batch_id}/status until complete
# 3. Assert: all 50 records have recovery_state != "INGESTED"
# 4. Assert: recovered_gmv is within expected range (₹1.8L–₹2.3L)
# 5. Assert: recovery_rate is within 62%–72%
# 6. Assert: all Hard Decline records are FAILED_STOPPED with zero cost
# 7. Assert: all records have at least 2 audit trail entries (INGESTED + CLASSIFIED)
# 8. POST /api/recovery/{random_id}/opt-out → assert state changes
# 9. GET /api/audit/{random_id} → assert entries are chronologically ordered
```

### Step 9.2: UI Polish
- Add loading skeletons for Kanban cards during batch processing
- Add tooltip on metric cards explaining the calculation
- Responsive layout: sidebar collapses to bottom sheet on mobile
- Keyboard shortcut: `B` to trigger batch run, `Esc` to close modals
- Favicon and page title: "RecoverOS — Revenue Recovery Dashboard"

### Step 9.3: Documentation

#### [NEW] `README.md` (project root)
- Project title, tagline, architecture diagram
- Quick start: prerequisites, env setup, backend start, frontend start
- Demo walkthrough with screenshots
- Tech stack table
- API reference link

#### [NEW] `docs/ARCHITECTURE.md`
- System architecture diagram (from blueprint §2)
- AI agent architecture (from blueprint §3)
- State machine diagram
- Data flow description

---

## Phase 10 — Deployment & Submission

> **Goal:** Deployed, recorded, submitted.

### Step 10.1: Deploy Backend
```bash
# Railway deployment
cd backend
railway login
railway init
railway up
# Set env vars in Railway dashboard
```

### Step 10.2: Deploy Frontend
```bash
# Vercel deployment
cd frontend
npx vercel --prod
# Set VITE_API_URL env var to Railway backend URL
```

### Step 10.3: Final Checklist Verification

Run through all 11 items from blueprint §12:
- [ ] 50-record batch with correct class distribution
- [ ] Razorpay test mode payment links + webhook loop
- [ ] AI architecture with rule/LLM boundary
- [ ] Guardrails: opt-out, retry cap, CAC ceiling, fraud halt
- [ ] Hinglish voice demo with TTS audio
- [ ] Dual-pane UI: Kanban + Phone simulator
- [ ] Settlement verification end-to-end
- [ ] Audit trail with LLM metadata + "why we didn't act"
- [ ] Probabilistic metrics (varying per run)
- [ ] 5-minute pitch video
- [ ] README + ARCHITECTURE.md + deployed links

---

## Verification Plan

### Automated Tests
```bash
cd backend
python -m pytest tests/ -v --tb=short
```
Tests cover: classifier accuracy, guardrail enforcement, state machine transitions, batch simulation metrics, E2E flow.

### Manual Verification
1. **Run batch via UI** → verify Kanban animation, metric updates, phone simulator interaction
2. **Click WhatsApp → Pay → Authorize UPI** → verify settlement loop completes
3. **Trigger all 3 edge cases** → verify graceful abort + audit entries
4. **Open Audit Inspector** for each failure class → verify entries are complete
5. **Run batch 3 times** → verify metrics vary slightly (probabilistic, not canned)

---

## Open Questions

> [!IMPORTANT]
> **Razorpay API Keys:** Do you have a Razorpay Test Mode account set up? I'll need the `rzp_test_...` key and secret to wire up payment link generation and webhook verification.

> [!IMPORTANT]
> **Gemini API Key:** Do you have a Google AI Studio API key for Gemini 2.0 Flash / 2.5 Pro? This is needed for the LLM agent functions (customer reply parsing, Hinglish script generation).

> [!NOTE]
> **Sarvam AI:** The Hinglish TTS can be **fully simulated** in the demo (using pre-recorded audio or browser-native `SpeechSynthesis` as fallback). A real Sarvam API key is optional for the hackathon. Should I mock the voice pipeline or integrate Sarvam directly?

> [!NOTE]
> **Deployment targets:** Plan assumes Vercel (frontend) + Railway (backend). Are these okay, or do you prefer alternatives (e.g., Render, Fly.io, self-hosted)?
