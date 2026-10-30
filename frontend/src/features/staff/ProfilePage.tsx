import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, CalendarDays, HeartPulse, Mail, MapPin, Phone, Target, User, Briefcase } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Field, Input, Select, Skeleton } from '@/components/ui'
import { useQueryClient } from '@tanstack/react-query'
import { saveMyDetails, useProfile, type Profile } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

const GENDERS = ['Male', 'Female', 'Other', 'Prefer not to say']

/** The employee's own details. The emergency contact must be given; the Aadhaar, PAN and UAN numbers are there to fill in. Their documents (Aadhaar, PAN, UAN, a photo) are uploaded under Documents. */
function MyDetails({ p }: { p: Profile }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ emergency_contact: p.emergency_contact ?? '', emergency_phone: p.emergency_phone ?? '', gender: p.gender ?? '', date_of_birth: p.date_of_birth ?? '', aadhaar_no: p.aadhaar_no ?? '', pan_no: p.pan_no ?? '', uan_no: p.uan_no ?? '', esi_no: p.esi_no ?? '' })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const [tried, setTried] = useState(false)
  const contactOk = f.emergency_contact.trim() !== '' && f.emergency_phone.replace(/\D/g, '').length >= 7
  const save = useAction(() => saveMyDetails(f), { success: (r) => r.message ?? 'Saved', onSuccess: () => { void qc.invalidateQueries({ queryKey: ['staff'] }) } })
  const missing = !p.emergency_complete
  return (
    <section aria-label="My details" className="mt-6 rounded-xl border border-border bg-card p-5 shadow-card">
      <h2 className="text-base font-semibold">My details</h2>
      <p className="mb-4 mt-1 text-sm text-muted-foreground">An emergency contact is required. Fill in your Aadhaar, PAN, UAN and ESI numbers here too. Your Aadhaar card, PAN card, UAN and photo are uploaded under <Link className="text-primary underline" to="/me/documents">Documents</Link> (a photo or a PDF).</p>
      {missing && <p role="alert" className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-sm">Please give an emergency contact{p.onboarding ? ' to finish onboarding' : ''}.</p>}
      <form onSubmit={(e) => { e.preventDefault(); setTried(true); if (contactOk) save.mutate() }} className="grid gap-4 sm:grid-cols-2" noValidate>
        <Field label="Emergency contact name *" htmlFor="md-name" error={tried && !f.emergency_contact.trim() ? 'Required.' : undefined}><Input id="md-name" value={f.emergency_contact} onChange={set('emergency_contact')} autoComplete="off" /></Field>
        <Field label="Emergency contact phone *" htmlFor="md-phone" error={tried && f.emergency_phone.replace(/\D/g, '').length < 7 ? 'Enter a phone number.' : undefined}><Input id="md-phone" type="tel" value={f.emergency_phone} onChange={set('emergency_phone')} autoComplete="off" /></Field>
        <Field label="Gender" htmlFor="md-gender" hint="Optional."><Select id="md-gender" value={f.gender} placeholder="Prefer not to say" onChange={set('gender')} options={GENDERS.map((g) => ({ value: g, label: g }))} /></Field>
        <Field label="Date of birth" htmlFor="md-dob" hint="Optional. Colleagues see the day and month, and wish you on the day."><Input id="md-dob" type="date" max={new Date().toISOString().slice(0, 10)} value={f.date_of_birth} onChange={set('date_of_birth')} /></Field>
        <Field label="Aadhaar number" htmlFor="md-aadhaar" hint="12 digits."><Input id="md-aadhaar" inputMode="numeric" value={f.aadhaar_no} onChange={set('aadhaar_no')} autoComplete="off" /></Field>
        <Field label="PAN" htmlFor="md-pan" hint="Like ABCDE1234F."><Input id="md-pan" value={f.pan_no} onChange={(e) => setF((s) => ({ ...s, pan_no: e.target.value.toUpperCase() }))} autoComplete="off" /></Field>
        <Field label="UAN" htmlFor="md-uan" hint="12 digits."><Input id="md-uan" inputMode="numeric" value={f.uan_no} onChange={set('uan_no')} autoComplete="off" /></Field>
        <Field label="ESI number" htmlFor="md-esi" hint="10 digits."><Input id="md-esi" inputMode="numeric" value={f.esi_no} onChange={set('esi_no')} autoComplete="off" /></Field>
        {save.error && <p role="alert" className="text-sm text-danger sm:col-span-2">{save.error.message}</p>}
        <div className="sm:col-span-2"><Button type="submit" loading={save.isPending}>Save my details</Button></div>
      </form>
    </section>
  )
}

/** What the business holds about the person. HR changes most of it; the person gives their own emergency contact and ID numbers. */
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
      <PageHeader eyebrow="My work" title="My Profile" description="What the business holds about you. HR changes most of it; your emergency contact and ID numbers are yours to give, below." />
      {q.isPending || !p ? <Skeleton className="h-64 w-full" /> : (
        <section aria-label="Profile" className="overflow-hidden rounded-xl border border-border bg-card shadow-card">
          <div className="flex flex-col items-center bg-info px-6 py-8 text-center text-white">
            <span className="grid size-20 place-items-center rounded-lg bg-white/15 text-2xl font-bold">{p.first_name.charAt(0)}</span>
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
      {p && <MyDetails key={`${p.emergency_contact}|${p.emergency_phone}|${p.gender}|${p.date_of_birth}|${p.aadhaar_no}|${p.pan_no}|${p.uan_no}`} p={p} />}
    </>
  )
}
