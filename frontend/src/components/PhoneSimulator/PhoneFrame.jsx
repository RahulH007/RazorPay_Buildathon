import { useState } from 'react';
import { MessageCircle, Phone, CreditCard, Smartphone, Sparkles } from 'lucide-react';
import WhatsAppScreen from './WhatsAppScreen';
import VoiceCallScreen from './VoiceCallScreen';
import UPIPayScreen from './UPIPayScreen';

const TABS = [
  { key: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
  { key: 'voice', label: 'Voice Call', icon: Phone },
  { key: 'upi', label: 'UPI Pay', icon: CreditCard },
];

export default function PhoneFrame({ selectedRecord, onSettle, onDTMF, onSelectDefaultRecord }) {
  const [activeTab, setActiveTab] = useState('whatsapp');

  const renderScreen = () => {
    if (!selectedRecord) {
      return (
        <div className="flex h-full flex-col items-center justify-center p-6 text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-blue-500/20 bg-blue-500/10 shadow-lg shadow-blue-500/10">
            <Smartphone size={28} strokeWidth={1.75} className="text-cyan-400" />
          </div>
          <h4 className="text-sm font-semibold text-white">Customer Phone Simulator</h4>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">
            Click any record on the Kanban pipeline board to preview the multi-rail recovery experience.
          </p>
          {onSelectDefaultRecord && (
            <button
              onClick={onSelectDefaultRecord}
              className="mt-5 flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-blue-600/30 hover:bg-blue-600/50 border border-blue-500/40 text-cyan-300 text-xs font-semibold transition-all"
            >
              <Sparkles size={12} />
              Preview Sample Customer
            </button>
          )}
        </div>
      );
    }

    switch (activeTab) {
      case 'whatsapp':
        return <WhatsAppScreen record={selectedRecord} onPayClick={() => setActiveTab('upi')} />;
      case 'voice':
        return <VoiceCallScreen record={selectedRecord} onDTMF={onDTMF} />;
      case 'upi':
        return <UPIPayScreen record={selectedRecord} onSettle={onSettle} />;
      default:
        return null;
    }
  };

  return (
    <div className="relative w-[320px] h-[620px] overflow-hidden rounded-[44px] border border-white/[0.14] bg-[#02042B] shadow-[0_24px_70px_rgba(2,4,43,0.95),inset_0_0_0_1px_rgba(255,255,255,0.06)] flex flex-col shrink-0">
      {/* Glow behind phone */}
      <div className="pointer-events-none absolute -inset-6 rounded-[56px] bg-gradient-to-b from-blue-600/15 via-cyan-500/10 to-transparent blur-2xl" />

      {/* Dynamic Island / Notch */}
      <div className="absolute left-1/2 top-2 z-30 h-5 w-28 -translate-x-1/2 rounded-full bg-black border border-white/[0.08] flex items-center justify-end px-2.5">
        <div className="w-2.5 h-2.5 rounded-full bg-[#071026] border border-white/20" />
      </div>

      {/* Status bar */}
      <div className="relative z-20 flex items-center justify-between px-7 pt-3.5 pb-1 select-none">
        <span className="text-[11px] font-semibold text-slate-200 font-mono">9:41</span>
        <div className="flex items-center gap-1.5 text-[10px] font-medium text-slate-400">
          <span>5G</span>
          <div className="w-5 h-2.5 rounded-sm border border-slate-400/80 p-0.5 flex items-center">
            <div className="h-full w-3/4 bg-emerald-400 rounded-2xs" />
          </div>
        </div>
      </div>

      {/* Active Record Indicator Pill */}
      {selectedRecord && (
        <div className="relative z-20 mx-4 mt-1 px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
          <span className="text-[10px] font-mono text-cyan-300 truncate max-w-[170px]">
            {selectedRecord.customer_name}
          </span>
          <span className="text-[10px] font-mono font-bold text-white">
            ₹{(selectedRecord.amount / 100).toLocaleString('en-IN')}
          </span>
        </div>
      )}

      {/* Main Screen Content */}
      <div className="relative flex-1 overflow-y-auto z-10">{renderScreen()}</div>

      {/* Bottom Navigation Tab Bar */}
      <div className="relative z-20 flex border-t border-white/[0.1] bg-[#071026]/95 backdrop-blur-xl">
        {TABS.map(({ key, label, icon: Icon }) => {
          const isActive = activeTab === key;
          return (
            <button
              key={key}
              className={`flex flex-1 flex-col items-center gap-1 py-2.5 transition-all ${
                isActive ? 'text-cyan-400' : 'text-slate-500 hover:text-slate-300'
              }`}
              onClick={() => setActiveTab(key)}
            >
              <div className={`p-1 rounded-lg transition-colors ${isActive ? 'bg-cyan-500/10' : ''}`}>
                <Icon size={16} strokeWidth={isActive ? 2.5 : 1.75} />
              </div>
              <span className="text-[9px] font-semibold tracking-tight">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}