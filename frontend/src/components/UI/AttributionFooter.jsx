/**
 * RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
 * Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
 *
 * Attribution stays on the page rather than living only in the repository, so
 * a screenshot, a recorded demo, or a deployed copy still names its author.
 */

import { ArrowUpRight } from 'lucide-react';

export const AUTHOR = 'Rahul Hongekar';
export const AUTHOR_GITHUB = 'RahulH007';
export const REPO_URL = 'https://github.com/RahulH007/RecoverOS';

export default function AttributionFooter() {
  return (
    <footer className="mt-12 border-t border-[var(--rzp-border)] bg-[var(--rzp-surface-alt)]">
      <div className="rzp-container flex flex-wrap items-center justify-between gap-3 py-6">
        <p className="text-xs text-[var(--rzp-ink-muted)]">
          <span className="font-semibold text-[var(--rzp-ink)]">RecoverOS</span>
          {' — built by '}
          <a
            className="rzp-link font-semibold"
            href={`https://github.com/${AUTHOR_GITHUB}`}
            target="_blank"
            rel="noreferrer"
          >
            {AUTHOR}
          </a>
          {' for the Razorpay Buildathon, Track 03.'}
        </p>

        <a
          className="inline-flex items-center gap-1.5 font-mono text-[11px] text-[var(--rzp-ink-faint)] transition-colors hover:text-[var(--rzp-blue-600)]"
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
        >
          github.com/{AUTHOR_GITHUB}
          <ArrowUpRight size={12} strokeWidth={2} />
        </a>
      </div>
    </footer>
  );
}
