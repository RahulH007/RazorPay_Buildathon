import { useEffect, useState } from 'react';
import { Phone, PhoneCall, Volume2, X, RotateCcw } from 'lucide-react';
import api from '../../utils/api';

export default function VoiceCallScreen({ record, onDTMF }) {
  const [callState, setCallState] = useState('incoming');
  const [lastDTMF, setLastDTMF] = useState(null);
  const [script, setScript] = useState('');

  useEffect(() => () => {
    window.speechSynthesis?.cancel();
  }, []);

  if (!record) return null;

  const handleAccept = async () => {
    setCallState('active');
    try {
      const voiceData = await api.getVoiceScript(record.payment_id);
      const generatedScript = voiceData.script || '';
      setScript(generatedScript);
      if (generatedScript && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(generatedScript);
        utterance.rate = 0.95;
        window.speechSynthesis.speak(utterance);
      }
    } catch {
      setScript(`Namaste ${record.customer_name} ji. RecoverOS Merchant se call hai. Aapki ₹${(record.amount/100).toLocaleString('en-IN')} ki payment incomplete reh gayi thi. Abhi payment karne ke liye 1 dabayein, delay karne ke liye 2 dabayein, ya opt out ke liye 9 dabayein.`);
    }
  };

  const handleDecline = () => {
    window.speechSynthesis?.cancel();
    setCallState('ended');
  };

  const handleDTMFPress = (key) => {
    setLastDTMF(key);
    if (onDTMF) onDTMF(record.payment_id, key);
    if (key === '9') {
      window.speechSynthesis?.cancel();
      setCallState('ended');
    }
  };

  if (callState === 'ended') {
    return (
      <div className="flex flex-col h-full items-center justify-center p-6 text-center bg-[#071026]">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-rose-500/10 border border-rose-500/30 mb-3 shadow-lg shadow-rose-500/10">
          <PhoneCall size={26} strokeWidth={2} className="text-rose-400" />
        </div>
        <div className="text-base font-bold text-white">Call Terminated</div>
        <div className="mt-2 text-xs text-slate-300 px-4 leading-relaxed">
          {lastDTMF === '9' ? 'Customer opted out via DTMF 9. Unsubscribed from future calls.' :
           lastDTMF === '1' ? 'Instant payment link dispatched via SMS.' :
           lastDTMF === '2' ? 'Promise-to-pay schedule recorded for tomorrow.' :
           'Call disconnected gracefully.'}
        </div>
        <button
          className="mt-6 flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-600/30 transition-all"
          onClick={() => { setCallState('incoming'); setLastDTMF(null); }}
        >
          <RotateCcw size={13} />
          Restart Call Simulator
        </button>
      </div>
    );
  }

  if (callState === 'incoming') {
    return (
      <div className="flex flex-col h-full items-center justify-between p-6 text-center bg-gradient-to-b from-[#071026] to-[#02042B]">
        <div className="pt-6">
          <div className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-cyan-400 text-white font-bold text-2xl shadow-xl shadow-cyan-500/20 mb-3">
            <span>R</span>
            <span className="absolute inset-0 rounded-full animate-ping bg-cyan-400/20" />
          </div>
          <div className="text-lg font-bold text-white">Razorpay Recovery</div>
          <div className="text-xs text-emerald-400 mt-0.5">Incoming Hinglish AI Call...</div>
          <div className="text-[10px] text-slate-400 mt-2 font-mono">Re: ₹{(record.amount/100).toLocaleString('en-IN')} Failed Mandate</div>
        </div>

        <div className="flex items-center gap-10 pb-4">
          <button
            className="flex flex-col items-center gap-1.5 group"
            onClick={handleDecline}
          >
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-400 group-hover:bg-rose-500/30 group-active:scale-95 transition-all shadow-lg shadow-rose-500/20">
              <X size={24} strokeWidth={2.5} />
            </div>
            <span className="text-[10px] text-slate-400">Decline</span>
          </button>

          <button
            className="flex flex-col items-center gap-1.5 group"
            onClick={handleAccept}
          >
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 group-hover:bg-emerald-500/30 group-active:scale-95 transition-all shadow-lg shadow-emerald-500/20 animate-pulse">
              <Phone size={24} strokeWidth={2.5} fill="currentColor" />
            </div>
            <span className="text-[10px] text-emerald-400 font-semibold">Answer</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-3 bg-[#071026] text-slate-100">
      {/* Call Header */}
      <div className="flex items-center justify-between pb-2 border-b border-white/[0.08] mb-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
            <Volume2 size={15} />
          </div>
          <div>
            <div className="text-xs font-bold text-white">In Call • {record.customer_name}</div>
            <div className="text-[10px] text-emerald-400 font-mono">00:18 (Active)</div>
          </div>
        </div>
        <button
          onClick={handleDecline}
          className="p-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20"
          title="Hang up"
        >
          <PhoneCall size={14} />
        </button>
      </div>

      {/* Voice Transcript Bubble */}
      <div className="flex-1 overflow-y-auto rounded-xl border border-white/[0.08] bg-[#02042B]/80 p-3 text-[11px] text-slate-300 leading-relaxed font-sans select-text">
        <div className="text-[9px] font-mono text-cyan-300 uppercase mb-1">Live Voice Stream</div>
        {script || `Namaste ${record.customer_name} ji, RecoverOS automated desk se call hai...`}
      </div>

      {/* DTMF Keypad */}
      <div className="mt-2 pt-2 border-t border-white/[0.08]">
        <div className="text-[9px] font-mono text-slate-400 mb-1.5 text-center">Interactive Keypad (DTMF)</div>
        <div className="grid grid-cols-3 gap-1.5">
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-blue-600/20 border border-white/[0.08] hover:border-blue-500/40 text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('1')}
          >
            <span className="text-sm font-bold font-mono">1</span>
            <span className="text-[8px] text-cyan-300">Pay Now</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-blue-600/20 border border-white/[0.08] hover:border-blue-500/40 text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('2')}
          >
            <span className="text-sm font-bold font-mono">2</span>
            <span className="text-[8px] text-amber-300">Delay</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('3')}
          >
            <span className="text-sm font-bold font-mono">3</span>
            <span className="text-[8px] text-slate-400">Agent</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('4')}
          >
            <span className="text-sm font-bold font-mono">4</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('5')}
          >
            <span className="text-sm font-bold font-mono">5</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('6')}
          >
            <span className="text-sm font-bold font-mono">6</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('7')}
          >
            <span className="text-sm font-bold font-mono">7</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] text-white transition-all active:scale-95"
            onClick={() => handleDTMFPress('8')}
          >
            <span className="text-sm font-bold font-mono">8</span>
          </button>
          <button
            className="flex flex-col items-center py-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-300 transition-all active:scale-95"
            onClick={() => handleDTMFPress('9')}
          >
            <span className="text-sm font-bold font-mono text-rose-400">9</span>
            <span className="text-[8px] text-rose-400 font-semibold">Opt Out</span>
          </button>
        </div>
      </div>
    </div>
  );
}