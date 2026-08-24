import { useState } from 'react';
import { Copy, Check, Terminal } from 'lucide-react';

export default function CodeTerminal({ 
  filename = 'webhook-handler.ts',
  className = ''
}) {
  const [copied, setCopied] = useState(false);

  const rawSnippet = `export async function POST(req: Request) {
  // Ingest failed payment webhook from Razorpay
  const event = await req.json();
  if (event.event === 'payment.failed') {
    // Autonomous diagnosis & multi-rail recovery
    await razorpayRecoveryEngine.diagnoseAndRecover(event.payload);
  }
  return Response.json({ status: 'queued' });
}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(rawSnippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`rounded-2xl border border-white/[0.12] bg-[#070D28]/95 backdrop-blur-xl overflow-hidden shadow-2xl ${className}`}>
      {/* Terminal Topbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.08] bg-white/[0.02]">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-rose-500/80 shadow-[0_0_6px_rgba(244,63,94,0.4)]" />
          <div className="w-3 h-3 rounded-full bg-amber-500/80 shadow-[0_0_6px_rgba(245,158,11,0.4)]" />
          <div className="w-3 h-3 rounded-full bg-emerald-500/80 shadow-[0_0_6px_rgba(16,185,129,0.4)]" />
          <span className="ml-2 text-xs font-mono font-medium text-slate-400 flex items-center gap-1.5">
            <Terminal size={12} className="text-cyan-400" />
            {filename}
          </span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-[11px] font-mono text-slate-400 hover:text-white px-2.5 py-1 rounded-md bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] transition-all"
          title="Copy snippet"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Body */}
      <pre className="p-4 font-mono text-xs leading-relaxed overflow-x-auto text-slate-300 select-text">
        <code>
          <div><span className="text-cyan-400 font-semibold">export async function</span> <span className="text-blue-400 font-semibold">POST</span>(req: <span className="text-emerald-300">Request</span>) &#123;</div>
          <div className="text-slate-500 italic">  // Ingest failed payment webhook from Razorpay</div>
          <div>  <span className="text-cyan-400 font-semibold">const</span> event = <span className="text-cyan-400 font-semibold">await</span> req.<span className="text-blue-300">json</span>();</div>
          <div>  <span className="text-cyan-400 font-semibold">if</span> (event.event === <span className="text-teal-300">&apos;payment.failed&apos;</span>) &#123;</div>
          <div className="text-slate-500 italic">    // Autonomous diagnosis &amp; multi-rail recovery</div>
          <div>    <span className="text-cyan-400 font-semibold">await</span> razorpayRecoveryEngine.<span className="text-blue-400 font-semibold">diagnoseAndRecover</span>(event.payload);</div>
          <div>  &#125;</div>
          <div>  <span className="text-cyan-400 font-semibold">return</span> Response.<span className="text-blue-300">json</span>(&#123; status: <span className="text-teal-300">&apos;queued&apos;</span> &#125;);</div>
          <div>&#125;</div>
        </code>
      </pre>
    </div>
  );
}