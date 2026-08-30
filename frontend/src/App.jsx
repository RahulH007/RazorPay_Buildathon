import { useState, useEffect, useCallback, useRef } from 'react';

// Components
import AttributionFooter from './components/UI/AttributionFooter';
import PhoneFrame from './components/PhoneSimulator/PhoneFrame';

// Views
import HomeView from './components/Views/HomeView';
import CommandCenterView from './components/Views/CommandCenterView';
import ConsoleView from './components/Views/ConsoleView';
import DocsView from './components/Views/DocsView';
import AboutRahulView from './components/Views/AboutRahulView';

// Icons
import { ArrowRight, ArrowUpRight, X } from 'lucide-react';

// Hooks
import useWebSocket from './hooks/useWebSocket';
import useBatchSimulation from './hooks/useBatchSimulation';

// API
import api from './utils/api';

const TERMINAL_STATES = new Set(['RECOVERED', 'FAILED_STOPPED']);

const NAV_ITEMS = [
  { key: 'home', label: 'Home' },
  { key: 'overview', label: 'Command Center' },
  { key: 'console', label: 'Engine' },
  { key: 'docs', label: 'Resources' },
  { key: 'about', label: 'About' },
];

function App() {
  const [recordMap, setRecordMap] = useState({});
  const [metrics, setMetrics] = useState(null);
  const [selectedRecordId, setSelectedRecordId] = useState(null);
  const [processingId, setProcessingId] = useState(null);
  const [progressLocal, setProgressLocal] = useState(null);
  const [activeNav, setActiveNav] = useState('home');
  const [simulatorOpen, setSimulatorOpen] = useState(false);

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

  // Previously this called api.optOut, which writes CUSTOMER_OPT_OUT with
  // actor="customer" - a system decision recorded as a customer request. In a
  // ledger built to prove who did what, that is the one bug that discredits
  // everything else, so the fraud halt now has its own endpoint and actor.
  const handleFraudAlert = async () => {
    const record = pickRandomIntervening((r) => r.failure_class !== 'HARD_DECLINE');
    if (!record) {
      alert('No eligible records to quarantine. Run a batch first.');
      return;
    }
    try {
      await api.quarantine(record.payment_id);
      setTimeout(fetchDashboard, 500);
    } catch (err) {
      console.warn('Quarantine error:', err);
    }
  };

  const records = Object.values(recordMap);

  // The Command Center's decision drawer owns the right half of the screen, so
  // the phone is a modal rather than a rail: opened from a recovery action, on
  // the record that action belongs to.
  const handleOpenSimulator = (record) => {
    if (record?.payment_id) setSelectedRecordId(record.payment_id);
    setSimulatorOpen(true);
  };

  const handleLaunchSimulator = () => {
    if (!selectedRecordId && records.length > 0) {
      setSelectedRecordId(records[0].payment_id);
    }
    setSimulatorOpen(true);
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
            {/* Wordmark only. The Razorpay logo used to sit here, which read as
                "this is a Razorpay product" rather than a submission to their
                buildathon. */}
            <button
              onClick={() => setActiveNav('home')}
              className="shrink-0 cursor-pointer text-[19px] font-extrabold tracking-tight text-[var(--rzp-ink)] transition-colors hover:text-[var(--rzp-blue-600)]"
            >
              Recover<span className="text-[var(--rzp-blue-600)]">OS</span>
            </button>

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
            {/* Login and Sign Up are gone: there are no accounts, and both
                buttons navigated somewhere unrelated to their label. */}
            <a
              href="https://github.com/RahulH007/RazorPay_Buildathon"
              target="_blank"
              rel="noreferrer"
              className="hidden items-center gap-1.5 text-sm font-semibold text-[var(--rzp-ink-muted)] transition-colors hover:text-[var(--rzp-blue-600)] sm:inline-flex"
            >
              <span>Source</span>
              <ArrowUpRight size={14} strokeWidth={2.5} />
            </a>

            <button
              onClick={() => setActiveNav('docs')}
              className="rzp-btn-secondary hidden sm:inline-flex"
            >
              How it works
            </button>

            <button onClick={handleLaunchSimulator} className="rzp-btn-primary">
              <span>Run demo</span>
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
        {activeNav === 'docs' && <DocsView onNavigateTab={setActiveNav} />}

        {/* Dynamic View 3: About Rahul */}
        {activeNav === 'about' && <div className="rzp-container py-8"><AboutRahulView onNavigateTab={setActiveNav} /></div>}

        {/* Dynamic View 4: Recovery Command Center */}
        {activeNav === 'overview' && (
          <div className="rzp-container py-6">
            <CommandCenterView
              metrics={metrics}
              records={records}
              isConnected={ws.isConnected}
              stateChange={ws.stateChange}
              isRunning={batch.isRunning}
              progress={activeProgress}
              processingId={processingId}
              onRunBatch={handleRunBatch}
              onOptOut={handleOptOut}
              onFraudAlert={handleFraudAlert}
              selectedRecordId={selectedRecordId}
              onSelectRecord={(record) => setSelectedRecordId(record.payment_id)}
              onOpenSimulator={handleOpenSimulator}
            />
          </div>
        )}
      </main>

      <AttributionFooter />

      {/* ================= PHONE SIMULATOR =================
          Still here, and now reachable at every width: the decision drawer
          takes the right side of the screen, so a docked rail would have been
          covered exactly when a reviewer wanted to look at both. It opens on
          the record whose recovery action was being read. */}
      {simulatorOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#02042B]/90 p-4 backdrop-blur-lg animate-overlay-in">
          <div className="relative flex flex-col items-center">
            <button
              onClick={() => setSimulatorOpen(false)}
              className="absolute -top-12 right-0 flex items-center gap-1 rounded-lg bg-white/[0.08] px-3 py-1.5 font-mono text-xs text-slate-300 hover:text-white"
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

    </div>
  );
}

export default App;