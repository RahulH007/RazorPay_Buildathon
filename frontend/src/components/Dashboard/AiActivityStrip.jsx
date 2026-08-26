import { useEffect, useState } from 'react';
import { Bot, GitBranch, Zap, ShieldBan } from 'lucide-react';
import api from '../../utils/api';

const cell = 'flex flex-col gap-0.5';
const label = 'text-[11px] font-medium text-[var(--rzp-ink-faint)]';
const value = 'font-mono text-lg font-bold tracking-tight text-[var(--rzp-ink)]';

export default function AiActivityStrip({ refreshKey }) {
  const [activity, setActivity] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getLlmActivity()
      .then((data) => {
        if (!cancelled) setActivity(data);
      })
      .catch(() => {
        if (!cancelled) setActivity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (!activity) return null;

  const { rule_engine: ruleEngine, llm_agent: llmAgent } = activity.classification_split;

  return (
    <section className="rzp-card mb-4 flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
      <span className="flex items-center gap-2 text-sm font-semibold text-[var(--rzp-ink)]">
        <Bot size={16} strokeWidth={2} className="text-violet-600" />
        AI activity
      </span>

      <div className={cell}>
        <span className={label}>Model calls</span>
        <span className={value}>{activity.total_calls}</span>
      </div>

      {/* The split is the honest part: most records never need the model, and
          saying so is more credible than implying every decision is AI. */}
      <div className={cell}>
        <span className={label}>
          <GitBranch size={10} strokeWidth={2} className="mr-1 inline" />
          Rules / model
        </span>
        <span className={value}>
          {ruleEngine} / {llmAgent}
        </span>
      </div>

      <div className={cell}>
        <span className={label}>
          <Zap size={10} strokeWidth={2} className="mr-1 inline" />
          Mean latency
        </span>
        <span className={value}>{activity.mean_latency_ms}ms</span>
      </div>

      <div className={cell}>
        <span className={label}>Tokens in / out</span>
        <span className={value}>
          {activity.total_input_tokens} / {activity.total_output_tokens}
        </span>
      </div>

      <div className={cell}>
        <span className={label}>
          <ShieldBan size={10} strokeWidth={2} className="mr-1 inline" />
          Copy rejected
        </span>
        <span className={value}>{activity.rejections}</span>
      </div>
    </section>
  );
}
