import { useState } from 'react';
import { Copy, Check, Terminal } from 'lucide-react';

// The snippet is the real handler, lightly trimmed, from
// backend/app/routes/webhooks.py. It used to be a TypeScript SDK call to a
// package that does not exist, on a project whose backend is Python - the
// first thing a reviewer who opened the repo would have noticed.
export default function CodeTerminal({
  filename = 'app/routes/webhooks.py',
  className = ''
}) {
  const [copied, setCopied] = useState(false);

  const rawSnippet = `@router.post("/webhooks/razorpay")
async def receive_webhook(req: Request):
    # Verify the exact bytes, before parsing.
    body = await req.body()
    sig = req.headers.get("X-Razorpay-Signature")

    if not verify_signature(body, sig):
        raise HTTPException(401, "Bad signature")

    event = (await req.json()).get("event")
    if event == "payment.captured":
        return await handle_captured(db, payload)`;

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
          <div><span className="text-amber-300">@router.post</span>(<span className="text-teal-300">&quot;/webhooks/razorpay&quot;</span>)</div>
          <div><span className="text-cyan-400 font-semibold">async def</span> <span className="text-blue-400 font-semibold">receive_webhook</span>(req: <span className="text-emerald-300">Request</span>):</div>
          <div className="text-slate-500 italic">    # Verify the exact bytes, before parsing.</div>
          <div>    body = <span className="text-cyan-400 font-semibold">await</span> req.<span className="text-blue-300">body</span>()</div>
          <div>    sig = req.headers.<span className="text-blue-300">get</span>(<span className="text-teal-300">&quot;X-Razorpay-Signature&quot;</span>)</div>
          <div>&nbsp;</div>
          <div>    <span className="text-cyan-400 font-semibold">if not</span> <span className="text-blue-400 font-semibold">verify_signature</span>(body, sig):</div>
          <div>        <span className="text-cyan-400 font-semibold">raise</span> <span className="text-emerald-300">HTTPException</span>(<span className="text-orange-300">401</span>, <span className="text-teal-300">&quot;Bad signature&quot;</span>)</div>
          <div>&nbsp;</div>
          <div>    event = (<span className="text-cyan-400 font-semibold">await</span> req.<span className="text-blue-300">json</span>()).<span className="text-blue-300">get</span>(<span className="text-teal-300">&quot;event&quot;</span>)</div>
          <div>    <span className="text-cyan-400 font-semibold">if</span> event == <span className="text-teal-300">&quot;payment.captured&quot;</span>:</div>
          <div>        <span className="text-cyan-400 font-semibold">return await</span> <span className="text-blue-400 font-semibold">handle_captured</span>(db, payload)</div>
        </code>
      </pre>
    </div>
  );
}