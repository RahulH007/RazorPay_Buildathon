import { useState } from 'react';
import { Sparkles, X, Send, Bot, User, ArrowRight, Zap, CheckCircle2 } from 'lucide-react';

export default function AskRayWidget({ onRunBatch, onNavigateTab }) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([
    {
      id: 1,
      sender: 'ray',
      text: 'Namaste! I am Ray, your Razorpay Recovery AI Assistant. Ask me anything about checkout failure diagnosis, recovery channels, or webhook integration.',
      time: 'Just now'
    }
  ]);

  const QUICK_QUESTIONS = [
    'How does the <18ms diagnostic model work?',
    'What happens when a customer presses DTMF 9?',
    'Show WhatsApp UPI recovery conversion rate',
    'Trigger a 50-record recovery simulation',
  ];

  const handleSend = (textToSend) => {
    const text = textToSend || query;
    if (!text.trim()) return;

    const userMsg = {
      id: Date.now(),
      sender: 'user',
      text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMsg]);
    setQuery('');

    setTimeout(() => {
      let reply = "I'm analyzing the Razorpay Recovery Engine pipeline for you.";
      
      if (text.includes('18ms') || text.includes('diagnostic')) {
        reply = "The ensemble classifier evaluates 50M+ Razorpay payment patterns across NPCI error codes, 3DS gateway response times, and account parameters in <18ms without blocking the main checkout thread.";
      } else if (text.includes('DTMF 9') || text.includes('opt out') || text.includes('opt-out')) {
        reply = "When a customer presses DTMF 9 during an interactive Hinglish voice call, RecoverOS immediately executes an immutable opt-out record in the cryptographic ledger and suppresses all further outreach.";
      } else if (text.includes('WhatsApp') || text.includes('conversion') || text.includes('rate')) {
        reply = "WhatsApp 1-Click UPI recovery achieves an average 64.2% reclaimed rate for authentication friction, allowing customers to complete payment without reloading complex web apps.";
      } else if (text.includes('simulation') || text.includes('batch')) {
        if (onRunBatch) onRunBatch();
        reply = "🚀 Batch simulation triggered! 50 records are now streaming through the recovery pipeline in real time. Switch to the Dashboard tab to watch them settle.";
      } else {
        reply = `Ray AI analyzed: "${text}". All recovery operations are HMAC-authenticated and bounded by deterministic financial safety thresholds.`;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          sender: 'ray',
          text: reply,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    }, 600);
  };

  return (
    <>
      {/* Floating Trigger Button (Matches Razorpay Screenshot 2) */}
      <div className="fixed bottom-5 right-5 z-40">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white hover:bg-slate-50 text-[#0C2340] text-xs font-bold border border-slate-200 shadow-xl hover:shadow-2xl transition-all duration-200 hover:-translate-y-0.5 cursor-pointer font-sans"
        >
          {/* Green 4-point sparkle icon as in Razorpay Ray button */}
          <span className="flex h-4 w-4 items-center justify-center text-emerald-500">
            <Sparkles size={16} strokeWidth={2.5} className="fill-emerald-500 text-emerald-500" />
          </span>
          <span className="tracking-tight text-sm font-extrabold text-[#0C2340]">
            Ask RAY
          </span>
        </button>
      </div>

      {/* Ray AI Chat Dialog */}
      {isOpen && (
        <div className="fixed bottom-20 right-5 z-50 w-full max-w-sm sm:max-w-md rounded-3xl border border-white/[0.12] bg-[#071026] shadow-2xl shadow-black/80 overflow-hidden flex flex-col h-[520px] animate-modal-in">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.08] bg-[#02042B]/90">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 text-white shadow-md">
                <Sparkles size={16} strokeWidth={2.5} />
              </div>
              <div>
                <div className="text-sm font-bold text-white flex items-center gap-1.5 font-sans">
                  <span>Ray AI Assistant</span>
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-emerald-500/10 border border-emerald-500/30 text-emerald-300">
                    Live
                  </span>
                </div>
                <div className="text-[10px] text-slate-400">Razorpay Recovery Intelligence</div>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Messages Feed */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar text-xs">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex gap-2.5 ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {m.sender === 'ray' && (
                  <div className="w-6 h-6 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0 mt-0.5">
                    <Bot size={13} />
                  </div>
                )}
                <div
                  className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 leading-relaxed ${
                    m.sender === 'user'
                      ? 'bg-[#0B72E7] text-white rounded-br-xs'
                      : 'bg-[#0C1E3A] text-slate-200 border border-white/[0.06] rounded-bl-xs'
                  }`}
                >
                  <div>{m.text}</div>
                  <div className="text-[9px] opacity-50 mt-1 text-right">{m.time}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Quick Prompts Carousel */}
          <div className="p-2.5 border-t border-white/[0.06] bg-[#02042B]/50 flex gap-1.5 overflow-x-auto custom-scrollbar">
            {QUICK_QUESTIONS.map((q, i) => (
              <button
                key={i}
                onClick={() => handleSend(q)}
                className="shrink-0 px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-blue-600/20 border border-white/[0.08] text-[10px] text-slate-300 hover:text-cyan-300 transition-all font-mono"
              >
                {q}
              </button>
            ))}
          </div>

          {/* Input Bar */}
          <div className="p-3 border-t border-white/[0.08] bg-[#071026] flex items-center gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Ask Ray about failure diagnostics or recovery..."
              className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400"
            />
            <button
              onClick={() => handleSend()}
              className="p-2 rounded-xl bg-[#0B72E7] hover:bg-[#2B84EA] text-white transition-all shadow-md shadow-blue-500/20"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
