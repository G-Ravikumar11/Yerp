import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, ConfirmDialog, Field, Input, NumField, Select, Skeleton, Tabs } from '@/components/ui'
import { peopleKeys, resetPassword, setAccess, startOffboarding, updateEmployee, useDepartments, useEmployee, useEmployees, useHrCatalogue, type EmployeeDetail } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { AccessPicker } from './AccessPicker'
import { EMPLOYEE_TONE } from './EmployeesPage'

type Tab = 'profile' | 'access' | 'account' | 'onboarding'

function Profile({ e }: { e: EmployeeDetail }) {
  const depts = useDepartments()
  const people = useEmployees('')
  const cat = useHrCatalogue()
  const [f, setF] = useState({ first_name: e.first_name, last_name: e.last_name, email: e.email, phone: e.phone, job_title: e.job_title, department_id: e.department_id, reports_to: e.reports_to, level: e.level, role: e.role, employment_type: e.employment_type, pay_frequency: e.pay_frequency, salary: e.salary, tax_rate: e.tax_rate, start_date: e.start_date, emergency_contact: e.emergency_contact, emergency_phone: e.emergency_phone })
  const set = (k: keyof typeof f) => (ev: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: ev.target.value }))
  const save = useAction(() => updateEmployee(e.id, f), { invalidate: [peopleKeys.all], success: 'Saved' })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="First name" htmlFor="ep-first"><Input id="ep-first" value={f.first_name} onChange={set('first_name')} /></Field>
        <Field label="Last name" htmlFor="ep-last"><Input id="ep-last" value={f.last_name} onChange={set('last_name')} /></Field>
        <Field label="Email (their login)" htmlFor="ep-email"><Input id="ep-email" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Phone" htmlFor="ep-phone"><Input id="ep-phone" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Job title" htmlFor="ep-title"><Input id="ep-title" value={f.job_title} onChange={set('job_title')} /></Field>
        <Field label="Department" htmlFor="ep-dept"><Select id="ep-dept" value={f.department_id ?? ''} onChange={(ev) => setF((s) => ({ ...s, department_id: ev.target.value ? Number(ev.target.value) : null }))} placeholder="None" options={(depts.data ?? []).map((d) => ({ value: d.id, label: d.name }))} /></Field>
        <Field label="Reports to" htmlFor="ep-mgr"><Select id="ep-mgr" value={f.reports_to ?? ''} onChange={(ev) => setF((s) => ({ ...s, reports_to: ev.target.value ? Number(ev.target.value) : null }))} placeholder="None" options={(people.data ?? []).filter((p) => p.id !== e.id).map((p) => ({ value: p.id, label: p.full_name }))} /></Field>
        <Field label="Level" htmlFor="ep-level"><Select id="ep-level" value={f.level} onChange={set('level')} placeholder="Not set" options={(cat.data?.levels ?? []).map((l) => ({ value: l.code, label: l.label }))} /></Field>
        <Field label="Reporting role" htmlFor="ep-role"><Select id="ep-role" value={f.role} onChange={set('role')} options={(cat.data?.roles ?? []).map((r) => ({ value: r.code, label: r.label }))} /></Field>
        <Field label="Start date" htmlFor="ep-start"><Input id="ep-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Salary" htmlFor="ep-salary"><NumField id="ep-salary" value={f.salary} onValue={(n) => setF((s) => ({ ...s, salary: n }))} /></Field>
        <Field label="Tax rate %" htmlFor="ep-tax"><NumField id="ep-tax" value={f.tax_rate} onValue={(n) => setF((s) => ({ ...s, tax_rate: n }))} /></Field>
        <Field label="Emergency contact" htmlFor="ep-em"><Input id="ep-em" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Emergency phone" htmlFor="ep-emp"><Input id="ep-emp" value={f.emergency_phone} onChange={set('emergency_phone')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
      </div>
    </div>
  )
}

function Access({ e }: { e: EmployeeDetail }) {
  const cat = useHrCatalogue()
  const [role, setRole] = useState(e.permission_role)
  const [granted, setGranted] = useState(e.permissions)
  useEffect(() => { setRole(e.permission_role); setGranted(e.permissions) }, [e.permission_role, e.permissions])
  const save = useAction(() => setAccess(e.id, { permission_role: role, permissions: granted }), { invalidate: [peopleKeys.all], success: 'Access updated' })
  if (!cat.data) return <Skeleton className="h-40 w-full" />
  return (
    <div>
      <AccessPicker catalogue={cat.data} role={role} granted={granted} onRole={(code, rights) => { setRole(code); setGranted(rights) }} onGranted={setGranted} />
      <p className="mt-3 text-[13px] text-muted-foreground">Sites: {e.all_sites || e.site_names.length === 0 ? 'every site' : e.site_names.join(', ')}</p>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save access</Button>
      </div>
    </div>
  )
}

function Account({ e }: { e: EmployeeDetail }) {
  const [pw, setPw] = useState('')
  const [asking, setAsking] = useState(false)
  const reset = useAction(() => resetPassword(e.id, pw), { success: 'Password updated', onSuccess: () => setPw('') })
  const off = useAction(() => startOffboarding(e.id), { invalidate: [peopleKeys.all], onSuccess: () => setAsking(false) })
  return (
    <div className="max-w-md space-y-8">
      <div>
        <h3 className="mb-2 font-semibold">Reset their password</h3>
        <Field label="New password" htmlFor="ea-pw" hint="At least four characters. Tell them; it cannot be shown again."><Input id="ea-pw" type="text" autoComplete="off" value={pw} onChange={(ev) => setPw(ev.target.value)} /></Field>
        {reset.error && <p role="alert" className="mt-2 text-[13px] text-danger">{reset.error.message}</p>}
        <Button className="mt-3" loading={reset.isPending} disabled={pw.length < 4} onClick={() => reset.mutate()}>Set the password</Button>
      </div>
      {(e.status === 'active' || e.status === 'onboarding') && (
        <div>
          <h3 className="mb-2 font-semibold">Leaving</h3>
          <p className="mb-3 text-[13px] text-muted-foreground">Starts offboarding: the exit checklist, and their access ends when it is completed.</p>
          <Button variant="outline" className="text-danger" onClick={() => setAsking(true)}>Start offboarding</Button>
        </div>
      )}
      <ConfirmDialog open={asking} onOpenChange={setAsking} title={`Start offboarding ${e.full_name}?`} confirmLabel="Start offboarding" tone="danger" loading={off.isPending} onConfirm={() => off.mutate()} />
    </div>
  )
}

export default function EmployeePage() {
  const id = Number(useParams().id)
  const q = useEmployee(id)
  const [tab, setTab] = useState<Tab>('profile')
  const e = q.data
  if (q.isPending) return <Skeleton className="h-64 w-full" />
  if (!e) return <p role="alert" className="py-10 text-center text-sm text-danger">Could not open that employee.</p>
  return (
    <>
      <Link to="/people/employees" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Employees</Link>
      <PageHeader eyebrow={e.employee_id} title={e.full_name} description={[e.job_title, e.department_name, e.manager_name && `reports to ${e.manager_name}`].filter(Boolean).join(' · ') || undefined} actions={<Badge tone={EMPLOYEE_TONE[e.status] ?? 'neutral'}>{e.status}</Badge>} />
      <div className="mb-5"><Tabs label="Section" value={tab} onChange={setTab} items={[{ value: 'profile', label: 'Profile' }, { value: 'access', label: 'Access' }, { value: 'account', label: 'Account' }, { value: 'onboarding', label: `Onboarding ${e.onboarding_items.filter((i) => !i.is_completed).length || ''}`.trim() }]} /></div>
      {tab === 'profile' && <Profile key={e.id} e={e} />}
      {tab === 'access' && <Access e={e} />}
      {tab === 'account' && <Account e={e} />}
      {tab === 'onboarding' && (
        <ul className="max-w-xl divide-y divide-border rounded-lg border border-border">
          {e.onboarding_items.length === 0 && <li className="p-4 text-sm text-muted-foreground">No onboarding checklist.</li>}
          {e.onboarding_items.map((i) => <li key={i.id} className="flex items-center gap-3 px-4 py-2.5 text-sm"><input type="checkbox" readOnly checked={i.is_completed} aria-label={i.title} className="size-4 accent-[var(--primary)]" /><span className="flex-1">{i.title}</span><Badge>{i.category}</Badge><span className="w-16 text-right text-xs text-muted-foreground">{i.assigned_to}</span></li>)}
        </ul>
      )}
    </>
  )
}
