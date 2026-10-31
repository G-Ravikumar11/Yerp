import { Link } from 'react-router-dom'
import { useCelebrations } from '@/api/celebrations'

/** A strip on the front page when somebody has a birthday or it is a special day: it opens the Celebrations page. Nothing when there is nothing. */
export function CelebrationsBanner() {
  const { data } = useCelebrations()
  if (!data?.today.length) return null
  return (
    <Link to="/celebrations" className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-primary/30 bg-primary-soft/40 px-4 py-3 text-sm transition-colors hover:bg-primary-soft/70">
      {data.today.map((c) => <span key={c.key} className="font-medium"><span aria-hidden>{c.emoji}</span> {c.title}</span>)}
      <span className="ml-auto text-[12px] text-primary">Send wishes</span>
    </Link>
  )
}
