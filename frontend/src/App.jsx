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
  Smartphone,
  Headphones,
  X
} from 'lucide-react';

// Hooks
import useWebSocket from './hooks/useWebSocket';
import useBatchSimulation from './hooks/useBatchSimulation';

// API
import api from './utils/api';

const TERMINAL_STATES = new Set(['RECOVERED', 'FAILED_STOPPED']);

const NAV_ITEMS = [
  { key: 'home', label: 'Home', icon: Home },
  { key: 'overview', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'console', label: 'Console (Engine)', icon: Terminal },
  { key: 'docs', label: 'Docs', icon: BookOpen },
  { key: 'about', label: 'About Rahul', icon: User },
];

// All pages use the official Razorpay white theme
const LIGHT_THEME_TABS = new Set(['home', 'overview', 'console', 'docs', 'about']);

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

  const isLightTheme = LIGHT_THEME_TABS.has(activeNav);

  return (
    <div className={`min-h-screen flex flex-col font-sans transition-colors duration-300 ${
      isLightTheme
        ? 'bg-white text-[#0C2340] selection:bg-blue-500/20'
        : 'bg-[#02042B] text-slate-100 selection:bg-cyan-500/30 selection:text-white'
    }`}>
      {/* ================= STICKY HEADER (Razorpay.com Official Style) ================= */}
      <header className={`sticky top-0 z-40 flex h-16 shrink-0 items-center justify-between px-4 sm:px-6 lg:px-8 transition-colors duration-300 ${
        isLightTheme
          ? 'bg-white/95 border-b border-slate-200 backdrop-blur-lg shadow-sm'
          : 'bg-[#071026]/85 border-b border-white/[0.08] backdrop-blur-xl'
      }`}>
        {/* Left: Razorpay Brand Logo */}
        <div className="flex items-center gap-3">
          <RazorpayLogo isLight={isLightTheme} />
        </div>

        {/* Center: Navigation Bar (Matches Razorpay.com text-link style) */}
        <nav className="hidden md:flex items-center gap-1">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-all duration-200 cursor-pointer ${
                isLightTheme
                  ? activeNav === key
                    ? 'bg-[#0B72E7] text-white shadow-sm'
                    : 'text-[#334155] hover:text-[#0C2340] hover:bg-slate-100'
                  : activeNav === key
                    ? 'bg-blue-600/20 text-cyan-300 border border-blue-500/40 shadow-sm shadow-blue-500/10'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
              }`}
              onClick={() => setActiveNav(key)}
            >
              <Icon size={14} strokeWidth={2} />
              {label}
            </button>
          ))}
        </nav>

        {/* Right: Support, Country, Login, Sign Up (Matches Razorpay.com) */}
        <div className="flex items-center gap-2 sm:gap-3">
          <button 
            title="Support"
            onClick={() => setActiveNav('docs')}
            className={`p-1.5 rounded-lg transition-colors hidden sm:flex items-center cursor-pointer ${
              isLightTheme
                ? 'text-[#475569] hover:text-[#0C2340] hover:bg-slate-100'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Headphones size={18} />
          </button>

          <div className={`hidden sm:flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold ${
            isLightTheme
              ? 'bg-white border border-slate-200 text-[#0C2340]'
              : 'bg-white/[0.03] border border-white/[0.06] text-slate-200'
          }`}>
            <span>🇮🇳</span>
            <span className={`text-[10px] ${isLightTheme ? 'text-slate-400' : 'text-slate-400'}`}>▾</span>
          </div>

          <button
            onClick={() => setActiveNav('overview')}
            className={`px-4 py-1.5 rounded-lg text-[13px] font-bold transition-colors hidden sm:inline-flex cursor-pointer ${
              isLightTheme
                ? 'border border-slate-300 text-[#0C2340] hover:bg-slate-50'
                : 'border border-blue-500/40 text-cyan-300 hover:bg-blue-600/10'
            }`}
          >
            Login
          </button>

          <button
            onClick={handleLaunchSimulator}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0B72E7] hover:bg-[#0055D4] text-white text-[13px] font-bold shadow-md shadow-blue-600/20 transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
          >
            <span>Sign Up</span>
            <ArrowRight size={13} strokeWidth={2.5} />
          </button>
        </div>
      </header>

      {/* ================= MAIN CONTAINER ================= */}
      <main className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Dynamic View 0: Home Page (Sovereign AI Hero & Interactive Simulator) */}
        {activeNav === 'home' && (
          <HomeView 
            onNavigateTab={setActiveNav}
            onRunBatch={handleRunBatch}
            metrics={metrics}
          />
        )}

        {/* Dynamic View 1: Console / Telemetry */}
        {activeNav === 'console' && (
          <ConsoleView 
            records={records} 
            isConnected={ws.isConnected} 
            onRunBatch={handleRunBatch}
            isRunning={batch.isRunning}
          />
        )}

        {/* Dynamic View 2: Docs */}
        {activeNav === 'docs' && <DocsView />}

        {/* Dynamic View 3: About Rahul */}
        {activeNav === 'about' && <AboutRahulView />}

        {/* Dynamic View 4: Primary Overview Dashboard */}
        {activeNav === 'overview' && (
          <div className="flex flex-col xl:flex-row gap-6 items-start">
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
                      <span className="text-[#1B1F36]">Autonomous Revenue Recovery</span>
                      <br />
                      <span className="text-[#2563EB]">
                        Engineered for Scale.
                      </span>
                    </h1>

                    <p className="mt-4 text-sm sm:text-base leading-relaxed text-[#64748B] max-w-xl">
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
                        <span className="text-[10px] font-mono text-[#64748B] block">AI DIAGNOSIS</span>
                        <span className="text-xs font-mono font-bold text-[#2563EB]">14.2ms avg</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[#64748B] block">RECOVERED (UPI)</span>
                        <span className="text-xs font-mono font-bold text-emerald-600">₹4,990 Instant</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[#64748B] block">ACTIVE CHANNELS</span>
                        <span className="text-xs font-mono font-bold text-violet-600">WhatsApp / Voice</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#F8FAFC] border border-slate-100">
                        <span className="text-[10px] font-mono text-[#64748B] block">ENCRYPTED AUDIT</span>
                        <span className="text-xs font-mono font-bold text-[#2563EB]">100% Immutable</span>
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

              {/* 5-Stage Kanban Pipeline Board */}
              <section>
                <KanbanBoard 
                  records={records} 
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