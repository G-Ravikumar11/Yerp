import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Skeleton } from '@/components/ui'
import { useTeam } from '@/api/staff'

/** Who in the department is working right now. */
export default function TeamPage() {
  const q = useTeam()
  return (
    <>
      <PageHeader eyebrow="My work" title="My Team" description="Who in your department is in, on a break or away." />
      {q.isPending ? <Skeleton className="h-40 w-full" /> : q.data?.length ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {q.data.map((t) => (
            <section key={t.id} aria-label={t.name} className="rounded-xl border border-border bg-card p-4 shadow-card">
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-xl bg-primary-soft font-semibold text-primary">{t.name.charAt(0)}</span>
                <div className="min-w-0 flex-1"><p className="truncate font-medium">{t.name}</p><p className="truncate text-xs text-muted-foreground">{t.job_title || 'Team member'}</p></div>
                <Badge tone={t.is_online ? (t.is_on_break ? 'warning' : 'success') : 'neutral'} dot>{t.is_online ? (t.is_on_break ? 'On a break' : 'Working') : 'Away'}</Badge>
              </div>
              {t.clock_in && <p className="mt-2 text-xs text-muted-foreground">In since {t.clock_in.slice(0, 5)}</p>}
            </section>
          ))}
        </div>
      ) : <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No team members found. You appear here once you are in a department.</p>}
    </>
  )
}
