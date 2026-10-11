import { Building2, CalendarDays, HeartPulse, Mail, MapPin, Phone, Target, User, Briefcase } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui'
import { useProfile } from '@/api/staff'
import { formatDate } from '@/lib/format'

/** What the business holds about the person. Changes go through HR. */
export default function ProfilePage() {
  const q = useProfile()
  const p = q.data
  const rows = p ? [
    { icon: Mail, label: 'Email', value: p.email },
    { icon: Phone, label: 'Phone', value: p.phone || 'Not set' },
    { icon: Building2, label: 'Department', value: p.department || 'Not assigned' },
    { icon: User, label: 'Manager', value: p.manager || 'Not assigned' },
    { icon: CalendarDays, label: 'Start date', value: p.start_date ? formatDate(p.start_date) : 'Not set' },
    { icon: MapPin, label: 'Work location', value: p.work_location || 'Office' },
    { icon: Briefcase, label: 'Employment', value: (p.employment_type || '').replace('_', ' ') || 'Not set' },
    { icon: HeartPulse, label: 'Emergency contact', value: [p.emergency_contact, p.emergency_phone].filter(Boolean).join(' - ') || 'Not set' },
  ] : []
  return (
    <>
      <PageHeader eyebrow="My work" title="My Profile" description="What the business holds about you. To change any of it, ask HR." />
      {q.isPending || !p ? <Skeleton className="h-64 w-full" /> : (
        <section aria-label="Profile" className="overflow-hidden rounded-xl border border-border bg-card shadow-card">
          <div className="flex flex-col items-center bg-gradient-to-br from-steel-500 to-steel-600 px-6 py-8 text-center text-white">
            <span className="grid size-20 place-items-center rounded-2xl bg-white/15 text-2xl font-bold">{p.first_name.charAt(0)}</span>
            <h2 className="mt-3 text-xl font-semibold">{p.full_name}</h2>
            <p className="text-sm text-white/70">{p.job_title}{p.department && ` - ${p.department}`}</p>
            <p className="mt-1 font-mono text-xs text-white/60">{p.employee_id_code}</p>
          </div>
          <dl className="grid gap-3 p-5 sm:grid-cols-2">
            {rows.map(({ icon: Icon, label, value }) => (
              <div key={label} className="flex items-start gap-3 rounded-lg bg-muted/50 p-3"><span className="grid size-9 shrink-0 place-items-center rounded-md bg-card text-primary shadow-xs"><Icon className="size-4" /></span><div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-words text-sm font-medium">{value}</dd></div></div>
            ))}
            {p.goals_count > 0 && <div className="flex items-center gap-3 rounded-lg bg-primary-soft p-3 sm:col-span-2"><span className="grid size-9 place-items-center rounded-md bg-card text-primary"><Target className="size-4" /></span><p className="text-sm"><strong>{p.goals_count}</strong> goal{p.goals_count === 1 ? '' : 's'} set - <strong>{p.goal_progress}%</strong> on average</p></div>}
          </dl>
        </section>
      )}
    </>
  )
}
