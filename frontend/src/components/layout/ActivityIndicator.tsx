import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useIsFetching, useIsMutating } from '@tanstack/react-query'
import { cn } from '@/lib/utils'

const SHOW_AFTER_MS = 200      // a request that answers at once never flashes the bar
const CRANE_AFTER_MS = 450     // the crane waits a little longer: only a load you would notice gets it
const HOLD_MS = 450            // and once shown, either stays long enough to be seen

/** `on`, steadied: it turns true only after `after` ms of being true, and false after HOLD_MS of being false. */
function useSteady(on: boolean, after: number) {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShown(on), on ? after : HOLD_MS)
    return () => clearTimeout(t)
  }, [on, after])
  return shown
}

/**
 * Two kinds of work. The thin bar shows for anything the app does: loading, refreshing in the background, saving.
 * The crane shows only while a screen is loading data it does not have yet - a reload, or opening a page for the
 * first time. A screen quietly refreshing what it already shows, or a save, never brings the crane up.
 */
function useBusy() {
  const anything = useIsFetching() + useIsMutating() > 0
  const firstLoad = useIsFetching({ predicate: (q) => q.state.data === undefined && q.state.status === 'pending' }) > 0
  return { bar: useSteady(anything, SHOW_AFTER_MS), crane: useSteady(firstLoad, CRANE_AFTER_MS) }
}

const NAVY = 'var(--crane-navy)'      // dark navy on a light page, pale grey-blue on a dark one
const BLUE = '#1f6fe0'
const SKY = '#4aa3f5'
const ORANGE = '#f08c2e'
const CRATE = '#b9c2cc'
const CRATE_EDGE = '#8a95a3'

/** The lattice of the mast: two rails and a zigzag between them. */
const MAST = (() => {
  const pts = ['M75 118']
  for (let y = 118, right = true; y > 52; y -= 6, right = !right) pts.push(`L${right ? 85 : 75} ${y - 6}`)
  return pts.join(' ')
})()
/** The truss under the jib. */
const TRUSS = (() => {
  const pts = ['M24 44']
  for (let x = 24, low = true; x < 104; x += 5, low = !low) pts.push(`L${x + 5} ${low ? 48 : 44}`)
  return pts.join(' ')
})()

function Crate({ x, y, className }: { x: number; y: number; className?: string }) {
  return (
    <g className={className}>
      <rect x={x} y={y} width="12" height="10" rx="1" fill={CRATE} stroke={CRATE_EDGE} strokeWidth="0.8" />
      <path d={`M${x} ${y + 5} H${x + 12} M${x + 6} ${y} V${y + 10}`} stroke={CRATE_EDGE} strokeWidth="0.6" />
    </g>
  )
}

/**
 * A tower crane at work: it lowers its hook, picks up a crate, slews round, sets it down on the other side and turns
 * back for the next one. The motion is in index.css (`.crane-*`); this draws the parts.
 */
function Crane() {
  return (
    <svg viewBox="0 0 160 132" className="w-24 text-foreground [--crane-navy:#c9d6e6]" role="img" aria-label="A tower crane moving a crate">
      <defs>
        <clipPath id="crane-below-jib">
          <rect x="0" y="47" width="160" height="85" />
        </clipPath>
      </defs>

      {/* the ground and the two places a crate is set down */}
      <rect x="14" y="124" width="132" height="2" rx="1" fill="currentColor" opacity="0.3" />
      <Crate x={33} y={114} className="crane-crate-left" />
      <Crate x={115} y={114} className="crane-crate-right" />

      {/* the mast stands still */}
      <rect x="69" y="118" width="22" height="6" rx="1.5" fill={NAVY} />
      <path d="M75 118 V50 M85 118 V50" stroke={BLUE} strokeWidth="1.6" />
      <path d={MAST} stroke={BLUE} strokeWidth="1" fill="none" />

      {/* everything above the turntable slews round together */}
      <g className="crane-slew">
        <path d={TRUSS} stroke={BLUE} strokeWidth="0.8" fill="none" opacity="0.8" />
        <rect x="22" y="40" width="84" height="4" rx="1" fill={BLUE} />
        <path d="M80 28 L26 40 M80 28 L104 40" stroke={NAVY} strokeWidth="0.7" opacity="0.7" />
        <path d="M76.5 42 L80 26 L83.5 42 Z" fill={ORANGE} />
        <rect x="71" y="44" width="18" height="6" rx="1.2" fill="#5b6b7d" />
        <rect x="82" y="45" width="8" height="7" rx="1.2" fill={NAVY} />
        <rect x="84" y="46.5" width="4" height="3" rx="0.6" fill={SKY} />
        <rect x="96" y="44" width="10" height="8" rx="1.2" fill={NAVY} />

        {/* the trolley, and the hook that goes down and up on its cable */}
        <rect x="35.5" y="43.5" width="7" height="3.5" rx="0.8" fill={NAVY} />
        <g clipPath="url(#crane-below-jib)">
          <g className="crane-hook">
            <line x1="39" y1="-40" x2="39" y2="58" stroke={NAVY} strokeWidth="0.8" />
            <path d="M35.5 58 L39 62 L42.5 58 Z" fill={ORANGE} />
            <Crate x={33} y={62} className="crane-crate-carried" />
          </g>
        </g>
      </g>
    </svg>
  )
}

/**
 * While any screen is loading or saving, a crane works in the middle of the page, with "Loading"
 * under it - so a slow page is never mistaken for a stuck one. It never blocks the page. A thin bar also runs along
 * the top of the window.
 */
export function ActivityIndicator() {
  const { bar, crane } = useBusy()
  if (typeof document === 'undefined') return null
  return createPortal(
    <>
      <div
        aria-hidden
        className={cn('pointer-events-none fixed inset-x-0 top-0 z-[70] h-0.5 overflow-hidden transition-opacity duration-300', bar ? 'opacity-100' : 'opacity-0')}
      >
        <div className="activity-bar h-full w-1/3 rounded-full bg-primary" />
      </div>
      <div
        role="status"
        aria-live="polite"
        aria-label={crane ? 'Loading' : undefined}
        className={cn('pointer-events-none fixed inset-0 z-[65] grid place-items-center transition-opacity duration-300', crane ? 'opacity-100' : 'opacity-0')}
      >
        {crane && (
          <div className="crane-pop flex flex-col items-center gap-1">
            <Crane />
            <p className="text-[9.5px] font-semibold uppercase tracking-[0.2em] text-foreground/70">
              Loading<span className="crane-dot">.</span><span className="crane-dot">.</span><span className="crane-dot">.</span>
            </p>
          </div>
        )}
      </div>
    </>,
    document.body,
  )
}
