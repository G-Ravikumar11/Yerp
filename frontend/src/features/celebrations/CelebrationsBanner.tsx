// Unused: celebrations moved into the Feed's Celebrations tab on 2026-11-01; nothing shows this banner.
export {}

// import { Link } from 'react-router-dom'
// import { useCelebrations } from '@/api/celebrations'
//
// const short = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
//
// /** A strip on the front page, every day: today's birthdays and special days, or - when there are none - what comes next. It opens the Celebrations page. */
// export function CelebrationsBanner() {
//   const { data, isPending } = useCelebrations()
//   if (isPending || !data) return <div className="mb-5 h-12 animate-pulse rounded-xl border border-border bg-muted/30" aria-hidden />
//   const next = data.upcoming[0]
//   return (
//     <Link to="/celebrations" aria-label="Celebrations" className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-primary/30 bg-primary-soft/40 px-4 py-3 text-sm transition-colors hover:bg-primary-soft/70">
//       {data.today.length > 0
//         ? data.today.map((c) => <span key={c.key} className="font-medium"><span aria-hidden>{c.emoji}</span> {c.title}</span>)
//         : <span className="text-muted-foreground"><span aria-hidden>🎉</span> No birthdays or special days today.{next ? ` Next: ${next.title}, ${short(next.date)}.` : ''}</span>}
//       <span className="ml-auto text-[12px] text-primary">{data.today.length > 0 ? 'Send wishes' : 'Open Celebrations'}</span>
//     </Link>
//   )
// }
