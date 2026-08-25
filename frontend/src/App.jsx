import { useState, useEffect, useCallback, useRef } from 'react';

// Components
import MetricRibbon from './components/Dashboard/MetricRibbon';
import KanbanBoard from './components/Dashboard/KanbanBoard';
import BatchControls from './components/Dashboard/BatchControls';
import ActivityTicker from './components/Dashboard/ActivityTicker';
import PhoneFrame from './components/PhoneSimulator/PhoneFrame';
import AuditModal from './components/AuditInspector/AuditModal';
import PillBadge from './components/UI/PillBadge';
import BentoCard from './components/UI/BentoCard';
import CodeTerminal from './components/UI/CodeTerminal';
import RazorpayLogo from './components/UI/RazorpayLogo';
import AskRayWidget from './components/UI/AskRayWidget';

// Views
import HomeView from './components/Views/HomeView';
import ConsoleView from './components/Views/ConsoleView';
import DocsView from './components/Views/DocsView';
import AboutRahulView from './components/Views/AboutRahulView';

// Icons
import { 
  Home,
  Zap, 
  LayoutDashboard, 
  Terminal, 
  BookOpen, 
  User, 
  ArrowRight,
  Headphones,
  ChevronDown,
  X
} from 'lucide-react';

// Hooks
import useWebSocket from './hooks/useWebSocket';
import useBatchSimulation from './hooks/useBatchSimulation';

// API
import api from './utils/api';

const TERMINAL_STATES = new Set(['RECOVERED', 'FAILED_STOPPED']);

const CLASS_FILTERS = [
  { key: 'ALL', label: 'All Payments' },
  { key: 'TRANSIENT_TECHNICAL', label: 'Transient' },
  { key: 'AUTH_FRICTION', label: 'Auth Friction' },
  { key: 'MANDATE_BALANCE', label: 'Mandate' },
  { key: 'B2B_RECEIVABLE', label: 'B2B' },
  { key: 'HARD_DECLINE', label: 'Hard Decline' },
];

const NAV_ITEMS = [
  { key: 'home', label: 'Home' },
  { key: 'overview', label: 'Recovery' },
  { key: 'console', label: 'Engine' },
  { key: 'docs', label: 'Resources' },
  { key: 'about', label: 'About' },
];

// All pages use the official Razorpay white theme
const BENTO_CARDS = [
  {
    icon: 'zap',
    iconColor: 'text-cyan-400',
    iconBg: 'bg-blue-600/10 border-blue-500/20',
    badgeLabel: '+24.8% Reclaimed',
    badgeColor: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
    title: 'Autonomous Fallback',
    description: 'Dynamically reroutes failed subscription mandates through secondary payment methods and localized UPI payment links.',
  },
  {
    icon: 'brain',
    iconColor: 'text-blue-400',
    iconBg: 'bg-violet-600/10 border-violet-500/20',
    badgeLabel: '94.2% Accuracy',
    badgeColor: 'bg-cyan-500/10 border-cyan-500/20 text-cyan-400',
    title: 'AI Diagnostics Engine',
    description: 'Classifies failure root causes in <18ms using ensemble models trained on 50M+ Razorpay transaction patterns.',
  },
  {
    icon: 'shield',
    iconColor: 'text-emerald-400',
    iconBg: 'bg-emerald-600/10 border-emerald-500/20',
    badgeLabel: '3-Rail Recovery',
    badgeColor: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
    title: 'Multi-Rail Recovery',
    description: 'Executes bounded recovery across WhatsApp, Hinglish Voice, and UPI resequence — each with independent audit trails.',
  },
];

function App() {
  const [recordMap, setRecordMap] = useState({});
  const [metrics, setMetrics] = useState(null);
  const [selectedRecordId, setSelectedRecordId] = useState(null);
  const [classFilter, setClassFilter] = useState('ALL');
  const [auditRecord, setAuditRecord] = useState(null);
  const [processingId, setProcessingId] = useState(null);
  const [progressLocal, setProgressLocal] = useState(null);
  const [activeNav, setActiveNav] = useState('home');
  const [mobileSimulatorOpen, setMobileSimulatorOpen] = useState(false);

  const phoneRef = useRef(null);
  const selectedRecord = recordMap[selectedRecordId] || null;

  const ws = useWebSocket();
  const batch = useBatchSimulation();

  const recordMapRef = useRef({});
  useEffect(() => {
    recordMapRef.current = recordMap;
  }, [recordMap]);

  const fetchDashboard = useCallback(async () => {
    try {
      const data = await api.getDashboardMetrics();
      setMetrics((prev) => ({ ...prev, ...data }));
      setRecordMap(Object.fromEntries((data.records || []).map((r) => [r.payment_id, r])));
      if (!selectedRecordId && data.records?.length > 0) {
        setSelectedRecordId(data.records[0].payment_id);
      }
    } catch {
      // Keep last known state on transient errors
    }
  }, [selectedRecordId]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    const progress = ws.batchProgress;
    if (!progress) return;
    const cur = progress.current_record;
    if (!cur?.payment_id) return;

    setProcessingId(cur.payment_id);
    setProgressLocal(progress);

    setRecordMap((prev) => {
      const existing = prev[cur.payment_id];
      if (!existing) {
        return {
          ...prev,
          [cur.payment_id]: {
            payment_id: cur.payment_id,
            amount: cur.amount ?? 0,
            method: cur.method || 'unknown',
            customer_name: cur.customer_name || 'Unknown',
            error_reason: cur.error_reason || 'unknown',
            error_description: null,
            failure_class: null,
            recovery_state: 'INGESTED',
            recovery_channel: null,
          },
        };
      }
      if (existing.recovery_state !== 'INGESTED') {
        return {
          ...prev,
          [cur.payment_id]: {
            ...existing,
            recovery_state: 'INGESTED',
            failure_class: null,
            recovery_channel: null,
            _movedAt: Date.now(),
          },
        };
      }
      return prev;
    });
  }, [ws.batchProgress]);

  useEffect(() => {
    if (!ws.stateChange) return;
    const { payment_id, from, to, details } = ws.stateChange;
    if (!payment_id || !to) return;

    setRecordMap((prev) => {
      const existing = prev[payment_id];
      if (!existing) return prev;

      if (TERMINAL_STATES.has(existing.recovery_state) && from !== 'INGESTED') {
        return prev;
      }

      return {
        ...prev,
        [payment_id]: {
          ...existing,
          recovery_state: to,
          failure_class: details?.failure_class ?? existing.failure_class,
          recovery_channel: details?.recovery_channel ?? existing.recovery_channel,
          customer_name: details?.customer_name ?? existing.customer_name,
          _movedAt: Date.now(),
          _lastActor: details?.actor ?? existing._lastActor,
        },
      };
    });

    if (TERMINAL_STATES.has(to)) {
      setProcessingId((pid) => (pid === payment_id ? null : pid));
    }
  }, [ws.stateChange]);

  useEffect(() => {
    if (ws.liveMetrics) {
      setMetrics((prev) => ({ ...prev, ...ws.liveMetrics }));
    }
  }, [ws.liveMetrics]);

  useEffect(() => {
    if (batch.batchStatus?.status === 'COMPLETED') {
      setProcessingId(null);
      fetchDashboard();
    }
  }, [batch.batchStatus, fetchDashboard]);

  useEffect(() => {
    if (batch.isRunning) {
      const interval = setInterval(fetchDashboard, 10000);
      return () => clearInterval(interval);
    }
  }, [batch.isRunning, fetchDashboard]);

  const activeProgress = ws.batchProgress || progressLocal || batch.batchStatus;

  const handleRunBatch = async () => {
    await batch.startBatch();
  };

  const handleCardClick = (record) => {
    setSelectedRecordId(record.payment_id);
    setAuditRecord(record);
  };

  const handleSettle = async (paymentId) => {
    try {
      await api.settle(paymentId);
      setTimeout(fetchDashboard, 500);
    } catch (err) {
      console.warn('Settlement error:', err);
    }
  };

  const handleDTMF = async (paymentId, key) => {
    try {
      await api.sendDTMF(paymentId, key);
      setTimeout(fetchDashboard, 500);
    } catch (err) {
      console.warn('DTMF error:', err);
    }
  };

  const pickRandomIntervening = (predicate = () => true) => {
    const candidates = Object.values(recordMapRef.current).filter(
      (r) => r.recovery_state === 'INTERVENING' && predicate(r)
    );
    if (candidates.length === 0) return null;
    return candidates[Math.floor(Math.random() * candidates.length)];
  };

  const handleOptOut = async () => {
    const record = pickRandomIntervening();
    if (!record) {
      alert('No records in INTERVENING state to opt out. Run a batch first!');
      return;
    }
    try {
      await api.optOut(record.payment_id);
      setTimeout(fetchDashboard, 500);
    } catch (err) {
      console.warn('Opt-out error:', err);
    }
  };

  const handleBankOutage = () => {
    alert('Bank outage drill initiated: Transient technical records held in retry queue until health check recovers.');
  };

  const handleFraudAlert = async () => {
    const record = pickRandomIntervening((r) => r.failure_class !== 'HARD_DECLINE');
    if (!record) {
      alert('No eligible records for fraud alert. Run a batch first!');
      return;
    }
    try {
      await api.optOut(record.payment_id);
      setTimeout(fetchDashboard, 500);
    } catch (err) {
      console.warn('Fraud alert error:', err);
    }
  };

  const records = Object.values(recordMap);
  const filteredRecords =
    classFilter === 'ALL'
      ? records
      : records.filter((r) => r.failure_class === classFilter);
  const latestRecordId =
    ws.stateChange?.payment_id ||
    [...records].reverse().find((r) => r.audit_trail !== undefined)?.payment_id ||
    records[0]?.payment_id;

  const openLatestAudit = () => {
    const target = latestRecordId ? recordMap[latestRecordId] : records[0];
    if (target) {
      setSelectedRecordId(target.payment_id);
      setAuditRecord(target);
    }
  };

  const handleLaunchSimulator = () => {
    if (window.innerWidth < 1280) {
      setMobileSimulatorOpen(true);
    } else if (phoneRef.current) {
      phoneRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };


  return (
    <div className="flex min-h-screen flex-col bg-white font-sans text-[var(--rzp-ink)] selection:bg-[var(--rzp-blue-050)]">
      {/* ================= STICKY HEADER (razorpay.com) =================
          Plain text nav, no icons and no active pill: Razorpay's header uses
          colour alone to mark the current section. Login is an outlined blue
          button, Sign Up is solid blue with a trailing arrow. */}
      <header className="sticky top-0 z-40 h-16 shrink-0 border-b border-[var(--rzp-border)] bg-white">
        <div className="mx-auto flex h-full max-w-[1280px] items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-8">
            <RazorpayLogo isLight />

            <nav className="hidden items-center gap-1 lg:flex">
              {NAV_ITEMS.map(({ key, label }) => (
                <button
                  key={key}
                  className="rzp-nav-link"
                  data-active={activeNav === key}
                  onClick={() => setActiveNav(key)}
                >
                  {label}
                </button>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <button
              title="Support"
              onClick={() => setActiveNav('docs')}
              className="hidden text-[var(--rzp-ink)] transition-colors hover:text-[var(--rzp-blue-600)] sm:flex cursor-pointer"
            >
              <Headphones size={20} strokeWidth={1.75} />
            </button>

            <button className="hidden items-center gap-1 text-[var(--rzp-ink-muted)] sm:flex cursor-pointer">
              <span className="text-lg leading-none">🇮🇳</span>
              <ChevronDown size={16} strokeWidth={2} />
            </button>

            <button
              onClick={() => setActiveNav('overview')}
              className="rzp-btn-secondary hidden sm:inline-flex"
            >
              Login
            </button>

            <button onClick={handleLaunchSimulator} className="rzp-btn-primary">
              <span>Sign Up</span>
              <ArrowRight size={15} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </header>

      {/* ================= MAIN CONTAINER ================= */}
      <main className="w-full flex-1">
        {/* Dynamic View 0: Home Page (Sovereign AI Hero & Interactive Simulator) */}
        {activeNav === 'home' && (
          <HomeView 
            onNavigateTab={setActiveNav}
            onRunBatch={handleRunBatch}
            metrics={metrics}
          />
        )}

        {/* Views other than Home render inside the shared content column;
            Home manages its own because its hero is full-bleed. */}
        {/* Dynamic View 1: Console / Telemetry */}
        {activeNav === 'console' && (
          <div className="rzp-container py-8"><ConsoleView 
            records={records} 
            isConnected={ws.isConnected} 
            onRunBatch={handleRunBatch}
            isRunning={batch.isRunning}
          /></div>
        )}

        {/* Dynamic View 2: Docs */}
        {activeNav === 'docs' && <div className="rzp-container py-8"><DocsView /></div>}

        {/* Dynamic View 3: About Rahul */}
        {activeNav === 'about' && <div className="rzp-container py-8"><AboutRahulView /></div>}

        {/* Dynamic View 4: Primary Overview Dashboard */}
        {activeNav === 'overview' && (
          <div className="rzp-container flex flex-col items-start gap-6 py-8 xl:flex-row">
            {/* Left Col: Main RecoverOS Dashboard */}
            <div className="flex-1 min-w-0 space-y-6">
              {/* Hero Section */}
              <section className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-gradient-to-br from-white via-[#F4F9FF] to-[#E8F3FF] p-6 sm:p-8 shadow-sm">
                {/* Atmospheric mesh light */}
                <div className="pointer-events-none absolute -top-24 -left-24 w-96 h-96 bg-blue-200/20 rounded-full blur-3xl" />
                <div className="pointer-events-none absolute -bottom-24 -right-24 w-96 h-96 bg-cyan-200/15 rounded-full blur-3xl" />

                <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
                  {/* Hero Left Content */}
                  <div className="lg:col-span-7">
                    <PillBadge 
                      label="Engine v3.0 is Live" 
                      linkLabel="View Docs →"
                      onLinkClick={() => setActiveNav('docs')}
                    />

                    <h1 className="mt-4 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight leading-[1.15]">
                      <span className="text-[var(--rzp-ink)]">Autonomous Revenue Recovery</span>
                      <br />
                      <span className="text-[var(--rzp-blue-600)]">
                        Engineered for Scale.
                      </span>
                    </h1>

                    <p className="mt-4 text-sm sm:text-base leading-relaxed text-[var(--rzp-ink-muted)] max-w-xl">
                      Detect failed Razorpay checkouts, diagnose root causes in &lt;18ms, re-engage customers via WhatsApp/Hinglish Voice, and eliminate churn — every rupee accounted for.
                    </p>

                    <BatchControls
                      onRunBatch={handleRunBatch}
                      isRunning={batch.isRunning}
                      progress={activeProgress}
                      onInspect={openLatestAudit}
                      onOptOut={handleOptOut}
                      onBankOutage={handleBankOutage}
                      onFraudAlert={handleFraudAlert}
                    />
                  </div>

                  {/* Hero Right: Developer Sandbox / Telemetry */}
                  <div className="lg:col-span-5 space-y-3">
                    <CodeTerminal filename="webhook-handler.ts" />
                    
                    {/* Live Telemetry Mini Grid */}
                    <div className="grid grid-cols-2 gap-2 p-3 rounded-2xl border border-slate-200 bg-white shadow-sm">
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[var(--rzp-ink-muted)] block">AI DIAGNOSIS</span>
                        <span className="text-xs font-mono font-bold text-[var(--rzp-blue-600)]">14.2ms avg</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[var(--rzp-ink-muted)] block">RECOVERED (UPI)</span>
                        <span className="text-xs font-mono font-bold text-emerald-600">₹4,990 Instant</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[var(--rzp-ink-muted)] block">ACTIVE CHANNELS</span>
                        <span className="text-xs font-mono font-bold text-violet-600">WhatsApp / Voice</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[var(--rzp-ink-muted)] block">ENCRYPTED AUDIT</span>
                        <span className="text-xs font-mono font-bold text-[var(--rzp-blue-600)]">100% Immutable</span>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* Bento Grid Features */}
              <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {BENTO_CARDS.map((card, i) => (
                  <BentoCard key={i} {...card} />
                ))}
              </section>

              {/* Stats Ribbon (6 Metric Bento Cards) */}
              <section>
                <MetricRibbon metrics={metrics} totalRecords={records.length} />
              </section>

              {/* 5-Stage Kanban Pipeline Board, filterable by failure class.
                  Razorpay uses this tab pattern to switch the content beneath
                  it, so it drives a real filter here rather than decorating. */}
              <section>
                <div className="mb-4 flex items-center gap-6 overflow-x-auto border-b border-[var(--rzp-border)]">
                  {CLASS_FILTERS.map(({ key, label }) => {
                    const count = key === 'ALL'
                      ? records.length
                      : records.filter((r) => r.failure_class === key).length;
                    return (
                      <button
                        key={key}
                        className="rzp-tab"
                        data-active={classFilter === key}
                        onClick={() => setClassFilter(key)}
                      >
                        {label}
                        <span className="ml-1.5 font-mono text-[11px] text-[var(--rzp-ink-faint)]">
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>

                <KanbanBoard 
                  records={filteredRecords} 
                  onCardClick={handleCardClick} 
                  processingId={processingId}
                  selectedRecordId={selectedRecordId}
                />
              </section>

              {/* Real-time Activity Ticker */}
              <section>
                <ActivityTicker stateChange={ws.stateChange} isConnected={ws.isConnected} />
              </section>
            </div>

            {/* Right Col: Sticky Desktop Phone Simulator Rail */}
            <aside ref={phoneRef} className="hidden xl:block shrink-0 sticky top-24">
              <PhoneFrame 
                selectedRecord={selectedRecord} 
                onSettle={handleSettle} 
                onDTMF={handleDTMF}
                onSelectDefaultRecord={() => {
                  if (records.length > 0) setSelectedRecordId(records[0].payment_id);
                }}
              />
            </aside>
          </div>
        )}
      </main>

      {/* ================= MOBILE SIMULATOR DRAWER ================= */}
      {mobileSimulatorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#02042B]/90 p-4 backdrop-blur-lg xl:hidden animate-overlay-in">
          <div className="relative flex flex-col items-center">
            <button
              onClick={() => setMobileSimulatorOpen(false)}
              className="absolute -top-12 right-0 flex items-center gap-1 text-xs font-mono text-slate-300 hover:text-white px-3 py-1.5 rounded-lg bg-white/[0.08]"
            >
              <X size={14} />
              Close Simulator
            </button>
            <PhoneFrame 
              selectedRecord={selectedRecord} 
              onSettle={handleSettle} 
              onDTMF={handleDTMF}
              onSelectDefaultRecord={() => {
                if (records.length > 0) setSelectedRecordId(records[0].payment_id);
              }}
            />
          </div>
        </div>
      )}

      {/* ================= AUDIT INSPECTOR MODAL ================= */}
      {auditRecord && <AuditModal record={auditRecord} onClose={() => setAuditRecord(null)} />}

      {/* ================= FLOATING ASK RAY AI WIDGET ================= */}
      <AskRayWidget onRunBatch={handleRunBatch} onNavigateTab={setActiveNav} />
    </div>
  );
}

export default App;