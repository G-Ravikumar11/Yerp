import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { appUrl } from '@/lib/paths'

interface Job {
  title: string; reference: string; location?: string; work_mode?: string; employment_type?: string; department?: string; level?: string
  salary_min: number | null; salary_max: number | null; salary_currency?: string; description?: string; requirements?: string
  closing_date?: string; apply_token?: string
}
interface Board { company?: string; logo_url?: string; jobs: Job[] }

const SYMBOLS: Record<string, string> = { GBP: '£', USD: '$', EUR: '€', INR: '₹', AUD: 'A$', CAD: 'C$' }
const money = (v: number, cur?: string) => (SYMBOLS[cur ?? ''] ?? (cur ? cur + ' ' : '')) + Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

function pay(j: Job): string {
  // Both come back null when the employer hides pay.
  if (j.salary_min === null || j.salary_max === null || (!j.salary_min && !j.salary_max)) return ''
  return j.salary_min && j.salary_max ? `${money(j.salary_min, j.salary_currency)} – ${money(j.salary_max, j.salary_currency)}` : money(j.salary_min || j.salary_max!, j.salary_currency)
}

/** A company's public careers page: the open roles, each with its own way to apply. */
export default function JobsPage() {
  const ref = new URLSearchParams(window.location.search).get('c')
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState(ref ? '' : 'This careers page needs a company reference in the link.')

  useEffect(() => {
    if (!ref) return
    api<Board>('/api/public/jobs/' + encodeURIComponent(ref), { quiet: true })
      .then((b) => { setBoard(b); document.title = `${b.company ? b.company + ' - ' : ''}Careers` })
      .catch(() => setError('We could not load these roles. Please check the link and try again.'))
  }, [ref])

  const jobs = board?.jobs ?? []
  return (
    <main className="mx-auto min-h-screen max-w-3xl bg-background px-4 py-10">
      <header className="mb-6 flex items-center gap-4">
        {board?.logo_url && <img src={board.logo_url} alt={board.company ?? ''} className="size-14 rounded-lg object-contain" />}
        <div><h1 className="text-2xl font-bold">{board?.company || 'Careers'}</h1><p className="text-sm text-muted-foreground">Open roles</p></div>
      </header>
      {error && <p role="alert" className="py-10 text-center text-muted-foreground">{error}</p>}
      {!error && !board && <p className="py-10 text-center text-muted-foreground">Loading open roles...</p>}
      {board && <p className="mb-4 text-sm text-muted-foreground">{jobs.length ? `${jobs.length} open role${jobs.length === 1 ? '' : 's'}` : ''}</p>}
      {board && jobs.length === 0 && <p className="py-10 text-center text-muted-foreground">There are no open roles right now.<br />Please check back soon.</p>}
      <div className="grid gap-4">
        {jobs.map((j) => {
          const seen = new Set<string>()
          // A remote role often has "Remote" as both location and work mode; showing it twice looks like a bug.
          const chips = [j.location, String(j.work_mode ?? '').replace('_', ' '), String(j.employment_type ?? '').replace('_', ' '), j.department, j.level].filter((c): c is string => {
            const k = String(c ?? '').trim().toLowerCase()
            if (!k || seen.has(k)) return false
            seen.add(k)
            return true
          })
          return (
            <article key={j.reference} className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold">{j.title}</h2><span className="text-xs text-muted-foreground">{j.reference}</span></div>
              <div className="my-2 flex flex-wrap gap-1.5 text-xs">
                {chips.map((c) => <span key={c} className="rounded-full bg-muted px-2.5 py-0.5">{c}</span>)}
                {pay(j) && <span className="rounded-full bg-success-soft px-2.5 py-0.5 text-success">{pay(j)}</span>}
              </div>
              {j.description && <p className="whitespace-pre-line text-sm">{j.description}</p>}
              {j.requirements && <details className="mt-2 text-sm"><summary className="cursor-pointer font-medium">What we are looking for</summary><p className="mt-1 whitespace-pre-line text-muted-foreground">{j.requirements}</p></details>}
              {j.closing_date && <p className="mt-2 text-xs text-muted-foreground">Closes {j.closing_date}</p>}
              {j.apply_token ? <a className="mt-3 inline-block text-sm font-semibold text-primary hover:underline" href={`${appUrl('apply')}?token=${encodeURIComponent(j.apply_token)}`}>Apply for this role &rarr;</a> : <span className="mt-3 inline-block text-sm text-muted-foreground">Applications not open yet</span>}
            </article>
          )
        })}
      </div>
    </main>
  )
}
