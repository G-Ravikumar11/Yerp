import { Link } from 'react-router-dom'
import { CheckCircle2, Circle } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui'
import { useOnboarding, useProfile } from '@/api/staff'

/** The tasks of settling in, and how many are done. */
export default function OnboardingPage() {
  const q = useOnboarding()
  const profile = useProfile()
  const items = q.data ?? []
  const done = items.filter((i) => i.is_completed).length
  const pct = items.length ? Math.round((done / items.length) * 100) : 0
  const C = 2 * Math.PI * 16
  return (
    <>
      <PageHeader eyebrow="My work" title="Onboarding" description="The tasks of settling in. HR ticks them off as they are done." />
      {profile.data && !profile.data.emergency_complete && (
        <p role="alert" className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">Your emergency contact is still needed - it is the one thing onboarding cannot finish without. <Link className="font-medium text-primary underline" to="/me/profile">Add it in My Profile</Link>. Your Aadhaar, PAN and UAN can be added there and under <Link className="font-medium text-primary underline" to="/me/documents">Documents</Link> whenever you like.</p>
      )}
      {q.isPending ? <Skeleton className="h-40 w-full" /> : (
        <>
          <section aria-label="Progress" className="mb-6 flex items-center gap-4 rounded-xl border border-border bg-card p-5 shadow-card">
            <div className="relative size-16">
              <svg viewBox="0 0 36 36" className="size-16 -rotate-90" aria-hidden><circle cx="18" cy="18" r="16" fill="none" strokeWidth="2.5" className="stroke-muted" /><circle cx="18" cy="18" r="16" fill="none" strokeWidth="2.5" strokeLinecap="round" className="stroke-primary" strokeDasharray={C} strokeDashoffset={C - (pct / 100) * C} /></svg>
              <span className="absolute inset-0 grid place-items-center text-sm font-bold text-primary">{pct}%</span>
            </div>
            <div><h2 className="font-semibold">Onboarding progress</h2><p className="text-sm text-muted-foreground">{done} of {items.length} tasks complete</p></div>
          </section>
          {items.length === 0 ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No onboarding items yet.</p> : (
            <ul className="grid gap-2">
              {items.map((i) => (
                <li key={i.id} className={`flex items-center gap-3 rounded-xl border border-border bg-card p-4 ${i.is_completed ? 'opacity-60' : ''}`}>
                  {i.is_completed ? <CheckCircle2 className="size-5 text-success" aria-label="Done" /> : <Circle className="size-5 text-muted-foreground" aria-label="Not done" />}
                  <div className="min-w-0 flex-1"><p className={`text-sm font-medium ${i.is_completed ? 'line-through' : ''}`}>{i.title}</p><p className="text-xs text-muted-foreground">{i.category}{i.assigned_to && ` - ${i.assigned_to}`}</p></div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  )
}
