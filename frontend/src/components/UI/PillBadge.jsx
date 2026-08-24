import { ExternalLink } from 'lucide-react';

export default function PillBadge({ 
  label = 'Engine v3.0 is Live', 
  linkLabel = 'View Docs →', 
  onLinkClick 
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-950/40 backdrop-blur-md px-3.5 py-1.5 shadow-inner shadow-blue-500/10">
      <span className="flex h-2 w-2 relative">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400" />
      </span>
      <span className="text-xs font-medium text-cyan-300">{label}</span>
      <span className="text-white/20">|</span>
      <button
        className="text-slate-300 hover:text-white cursor-pointer flex items-center gap-1 transition-colors"
        onClick={onLinkClick}
      >
        {linkLabel}
        <ExternalLink className="w-3 h-3" strokeWidth={2.5} />
      </button>
    </div>
  );
}