'use client';

import { X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useRecap } from '@/hooks/useRecap';
import { formatDuration } from '@/lib/recap';

/**
 * The card that closes the loop: two things the learner actually said, one
 * thing to practise, one sentence to say again.
 *
 * Renders nothing until the agent publishes a recap, so a failed publish is a
 * missing card rather than a broken session.
 */
export function SessionRecap() {
  const { recap, dismiss } = useRecap();

  const hasBody = Boolean(recap && (recap.wins.length > 0 || recap.focus || recap.drill));

  return (
    <AnimatePresence>
      {recap ? (
        <motion.aside
          key="recap"
          role="status"
          aria-live="polite"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
          className="bg-background/95 border-input/60 absolute inset-x-3 bottom-[150px] z-[60] mx-auto max-w-md rounded-2xl border p-4 shadow-lg backdrop-blur md:bottom-[190px]"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-muted-foreground font-mono text-[10px] font-bold tracking-wider uppercase">
                That&apos;s a wrap
              </p>
              <p className="text-foreground mt-0.5 text-sm font-semibold">
                {formatDuration(recap.durationSeconds)} of English
              </p>
            </div>
            <button
              type="button"
              onClick={dismiss}
              aria-label="Dismiss recap"
              className="text-muted-foreground hover:bg-accent hover:text-foreground -mt-1 -mr-1 rounded-full p-1.5 transition-colors"
            >
              <X className="size-4" />
            </button>
          </div>

          {recap.wins.length > 0 ? (
            <div className="mt-4">
              <p className="text-muted-foreground font-mono text-[10px] font-bold tracking-wider uppercase">
                You said
              </p>
              <ul className="mt-1.5 space-y-1.5">
                {recap.wins.map((win) => (
                  <li key={win.quote} className="text-sm leading-5">
                    <span className="text-foreground">&ldquo;{win.quote}&rdquo;</span>
                    {win.why ? <span className="text-muted-foreground"> — {win.why}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {recap.focus ? (
            <div className="mt-4">
              <p className="text-muted-foreground font-mono text-[10px] font-bold tracking-wider uppercase">
                Practise next
              </p>
              <p className="text-foreground mt-1 text-sm font-medium">{recap.focus.item}</p>
              <p className="text-muted-foreground mt-0.5 text-sm leading-5">
                {recap.focus.example}
              </p>
            </div>
          ) : null}

          {recap.drill ? (
            <div className="border-input/60 mt-4 rounded-xl border border-dashed p-3">
              <p className="text-muted-foreground font-mono text-[10px] font-bold tracking-wider uppercase">
                Say it once more
              </p>
              <p className="text-foreground mt-1 font-mono text-sm leading-5">
                {recap.drill.sentence}
              </p>
              {recap.drill.hint ? (
                <p className="text-muted-foreground mt-1 text-xs">{recap.drill.hint}</p>
              ) : null}
            </div>
          ) : null}

          {!hasBody ? (
            <p className="text-muted-foreground mt-4 text-sm leading-5">
              Nothing recorded this time — the next one is the one that counts.
            </p>
          ) : null}
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}
