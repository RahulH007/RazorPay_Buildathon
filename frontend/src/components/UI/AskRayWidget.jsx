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
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white hover:bg-slate-50 text-[var(--rzp-ink)] text-xs font-bold border border-slate-200 shadow-xl hover:shadow-2xl transition-all duration-200 hover:-translate-y-0.5 cursor-pointer font-sans"
        >
          {/* Green 4-point sparkle icon as in Razorpay Ray button */}
          <span className="flex h-4 w-4 items-center justify-center text-emerald-500">
            <Sparkles size={16} strokeWidth={2.5} className="fill-emerald-500 text-emerald-500" />
          </span>
          <span className="tracking-tight text-sm font-extrabold text-[var(--rzp-ink)]">
            Ask RAY
          </span>
        </button>
      </div>

      {/* Ray AI Chat Dialog */}
      {isOpen && (
        <div className="fixed bottom-20 right-5 z-50 flex h-[520px] w-full max-w-sm flex-col overflow-hidden rounded-2xl border border-[var(--rzp-border)] bg-white shadow-[0_24px_70px_rgba(22,47,86,0.18)] animate-modal-in sm:max-w-md">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--rzp-border)] px-5 py-4">
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
                <div className="text-[10px] text-[var(--rzp-ink-muted)]">Razorpay Recovery Intelligence</div>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="rounded-lg p-1.5 text-[var(--rzp-ink-muted)] transition-colors hover:bg-[var(--rzp-surface-alt)] hover:text-[var(--rzp-ink)]"
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
                      ? 'bg-[var(--rzp-blue-600)] text-white rounded-br-xs'
                      : 'bg-[var(--rzp-surface-alt)] text-[var(--rzp-ink)] border border-[var(--rzp-border)] rounded-bl-xs'
                  }`}
                >
                  <div>{m.text}</div>
                  <div className="text-[9px] opacity-50 mt-1 text-right">{m.time}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Quick Prompts Carousel */}
          <div className="custom-scrollbar flex gap-1.5 overflow-x-auto border-t border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)] p-2.5">
            {QUICK_QUESTIONS.map((q, i) => (
              <button
                key={i}
                onClick={() => handleSend(q)}
                className="shrink-0 rounded-lg border border-[var(--rzp-border)] bg-white px-2.5 py-1 font-mono text-[10px] text-[var(--rzp-ink-muted)] transition-colors hover:border-[var(--rzp-blue-600)] hover:text-[var(--rzp-blue-600)]"
              >
                {q}
              </button>
            ))}
          </div>

          {/* Input Bar */}
          <div className="flex items-center gap-2 border-t border-[var(--rzp-border)] bg-white p-3">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Ask Ray about failure diagnostics or recovery..."
              className="flex-1 rounded-xl border border-[var(--rzp-border)] bg-white px-3 py-2 text-xs text-[var(--rzp-ink)] placeholder-[var(--rzp-ink-faint)] focus:border-[var(--rzp-blue-600)] focus:outline-none"
            />
            <button
              onClick={() => handleSend()}
              className="rounded-xl bg-[var(--rzp-blue-600)] p-2 text-white transition-colors hover:bg-[var(--rzp-blue-700)]"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
