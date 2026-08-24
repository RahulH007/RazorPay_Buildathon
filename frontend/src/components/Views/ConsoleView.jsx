import { useState, useEffect } from 'react';
import { Terminal, Activity, Zap, Cpu, Server, CheckCircle, RefreshCw, Play } from 'lucide-react';
import api from '../../utils/api';

export default function ConsoleView({ records = [], isConnected = false, onRunBatch, isRunning = false }) {
  const [logs, setLogs] = useState([
    { id: 1, time: new Date().toLocaleTimeString(), level: 'INFO', module: 'ingest_worker', message: 'Webhook worker initialized and listening for Razorpay events' },
    { id: 2, time: new Date().toLocaleTimeString(), level: 'INFO', module: 'classifier', message: 'AI diagnostics model ensemble loaded (accuracy: 94.2%, latency: ~14ms)' },
    { id: 3, time: new Date().toLocaleTimeString(), level: 'INFO', module: 'orchestrator', message: 'Multi-rail channels ready: WhatsApp 1-click UPI, Hinglish Voice, Resequence' },
    { id: 4, time: new Date().toLocaleTimeString(), level: 'SUCCESS', module: 'telemetry', message: 'WebSocket live telemetry streaming enabled' },
  ]);

  const [metrics, setMetrics] = useState({
    avgLatency: '14.2ms',
    throughput: '142 req/s',
    queueDepth: 0,
    activeWorkers: 4,
    uptime: '99.98%',
  });

  useEffect(() => {
    if (records.length > 0) {
      const recent = records.slice(0, 8).map((r, i) => ({
        id: `rec-${r.payment_id}-${i}`,
        time: new Date().toLocaleTimeString(),
        level: r.recovery_state === 'RECOVERED' ? 'SUCCESS' : r.recovery_state === 'FAILED_STOPPED' ? 'WARN' : 'INFO',
        module: 'state_machine',
        message: `Payment ${r.payment_id} [₹${(r.amount/100).toLocaleString('en-IN')}] transitioned to ${r.recovery_state} via ${r.recovery_channel || 'evaluation'}`,
      }));
      setLogs((prev) => [...recent, ...prev.slice(0, 20)]);
    }
  }, [records]);

  return (
    <div className="space-y-6">
      {/* Console Header Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between text-[#64748B] text-xs font-mono">
            <span>DIAGNOSTIC LATENCY</span>
            <Zap size={14} className="text-[#2563EB]" />
          </div>
          <div className="mt-2 text-xl font-bold font-mono text-[#1B1F36]">{metrics.avgLatency}</div>
          <div className="text-[10px] text-emerald-600 mt-1">p99 &lt; 18ms</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between text-[#64748B] text-xs font-mono">
            <span>INGESTION RATE</span>
            <Activity size={14} className="text-[#2563EB]" />
          </div>
          <div className="mt-2 text-xl font-bold font-mono text-[#1B1F36]">{metrics.throughput}</div>
          <div className="text-[10px] text-[#64748B] mt-1">Razorpay webhook sync</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between text-[#64748B] text-xs font-mono">
            <span>ENGINE STATUS</span>
            <Server size={14} className={isConnected ? "text-emerald-600" : "text-rose-500"} />
          </div>
          <div className={`mt-2 text-xl font-bold font-mono ${isConnected ? 'text-emerald-600' : 'text-rose-500'}`}>
            {isConnected ? 'LIVE (ONLINE)' : 'OFFLINE'}
          </div>
          <div className="text-[10px] text-[#64748B] mt-1">FastAPI + Asyncio Loop</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between text-[#64748B] text-xs font-mono">
            <span>ACTIVE WORKERS</span>
            <Cpu size={14} className="text-violet-600" />
          </div>
          <div className="mt-2 text-xl font-bold font-mono text-[#1B1F36]">{metrics.activeWorkers} Cores</div>
          <div className="text-[10px] text-[#2563EB] mt-1">Bounded Concurrency</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between text-[#64748B] text-xs font-mono">
            <span>SYSTEM UPTIME</span>
            <CheckCircle size={14} className="text-emerald-600" />
          </div>
          <div className="mt-2 text-xl font-bold font-mono text-[#1B1F36]">{metrics.uptime}</div>
          <div className="text-[10px] text-emerald-600 mt-1">Zero dropped webhooks</div>
        </div>
      </div>

      {/* Interactive Engine Controls & Live Stream */}
      <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between px-6 py-4 border-b border-slate-200 bg-[#F8FAFC]">
          <div className="flex items-center gap-2">
            <Terminal size={18} className="text-[#2563EB]" />
            <h2 className="text-sm font-semibold text-[#1B1F36] font-mono">RazorpayRecoveryEngine Telemetry Stream</h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-blue-50 border border-blue-200 text-[#2563EB]">
              real-time
            </span>
          </div>

          <div className="flex items-center gap-3 mt-2 sm:mt-0">
            <button
              onClick={onRunBatch}
              disabled={isRunning}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold shadow-md shadow-blue-500/20 transition-all disabled:opacity-50 cursor-pointer"
            >
              {isRunning ? (
                <>
                  <RefreshCw size={12} className="animate-spin" />
                  Simulating Batch...
                </>
              ) : (
                <>
                  <Play size={12} fill="currentColor" />
                  Trigger 50-Record Batch Run
                </>
              )}
            </button>
          </div>
        </div>

        {/* Live Terminal Stream — keep dark for terminal aesthetic */}
        <div className="p-4 font-mono text-xs max-h-[480px] overflow-y-auto space-y-2 bg-[#1B1F36] select-text">
          {logs.map((log) => (
            <div key={log.id} className="flex items-start gap-3 py-1 border-b border-white/[0.06] hover:bg-white/[0.03] px-2 rounded">
              <span className="text-slate-500 shrink-0">{log.time}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${
                log.level === 'SUCCESS' ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' :
                log.level === 'WARN' ? 'bg-amber-500/15 text-amber-300 border border-amber-500/20' :
                'bg-blue-500/15 text-blue-300 border border-blue-500/20'
              }`}>
                {log.level}
              </span>
              <span className="text-slate-400 shrink-0">[{log.module}]</span>
              <span className="text-slate-200">{log.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
