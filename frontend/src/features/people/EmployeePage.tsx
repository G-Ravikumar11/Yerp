import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, ConfirmDialog, Field, Input, NumField, Select, Skeleton, Tabs, Textarea } from '@/components/ui'
import { deleteEmployee, setEmployeePassword, setEmployeeStatus, showEmployeeChange, updateEmployee, useDepartments, useEmployee, useEmployees, useHrCatalogue, type EmployeeDetail } from '@/api/people'
import { useQueryClient } from '@tanstack/react-query'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { EmployeeAccess } from './EmployeeAccess'
import { EmployeeDocuments } from './EmployeeDocuments'
import { GENDERS } from './EmployeeFormModal'
import { LoginEmail } from './LoginEmail'
import { SalaryIncrement } from './SalaryIncrement'
import { SetPasswordModal } from './SetPasswordModal'
import { EMPLOYEE_TONE } from './EmployeesPage'

type Tab = 'profile' | 'access'

function Profile({ e, ready, onPassword }: { e: EmployeeDetail; ready: boolean; onPassword: () => void }) {
  const { can, isHrOrMaster: hrOnly } = useSession()
  const canManage = can('people.manage')
  const [editing, setEditing] = useState(false)
  const cat = useHrCatalogue()
  type Row = [string, string | number | null | undefined]
  const personal: Row[] = [
    ['First name', e.first_name], ['Last name', e.last_name], ['Gender', e.gender], ['Email (their login)', e.email], ['Phone', e.phone], ['Address', e.address],
    ['Emergency contact', e.emergency_contact], ['Emergency phone', e.emergency_phone],
    // The ID numbers are HR's and the Master's.
    ...(hrOnly ? ([['Aadhaar (given by the employee)', e.aadhaar_masked], ['PAN (given by the employee)', e.pan_no], ['UAN (given by the employee)', e.uan_no], ['ESI number', e.esi_no]] as Row[]) : []),
  ]
  const company: Row[] = [
    ['Job title', e.job_title], ['Department', e.department_name], ['Reports to', e.manager_name],
    ['Level', cat.data?.levels.find((l) => l.code === e.level)?.label ?? e.level],
    ['Reporting role', cat.data?.roles.find((r) => r.code === e.role)?.label ?? e.role],
    ['Start date', e.start_date], ['Salary', e.salary], ['Tax rate %', e.tax_rate],
  ]
  if (editing) return <ProfileForm e={e} onDone={() => setEditing(false)} onPassword={onPassword} />
  const group = (title: string, rows: Row[], first = false) => (
    <section aria-label={title} className={first ? '' : 'mt-6 border-t border-border pt-5'}>
      <h4 className="mb-3 text-sm font-semibold">{title}</h4>
      <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[13px] text-muted-foreground">{label}</dt>
            <dd className="mt-0.5 text-sm">{value === null || value === undefined || value === '' ? '—' : value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
  return (
    <div>
      {canManage && <div className="mb-4 flex justify-end"><Button variant="outline" disabled={!ready} onClick={() => setEditing(true)}>Edit</Button></div>}
      {group('Personal details', personal, true)}
      {group('Company details', company)}
      {hrOnly && canManage && <LoginEmail e={e} />}
      {hrOnly && canManage && <SalaryIncrement e={e} />}
      {hrOnly && <EmployeeDocuments id={e.id} canManage={canManage} />}
    </div>
  )
}

function ProfileForm({ e, onDone, onPassword }: { e: EmployeeDetail; onDone: () => void; onPassword: () => void }) {
  const depts = useDepartments()
  const people = useEmployees('')
  const cat = useHrCatalogue()
  const [f, setF] = useState({ first_name: e.first_name, last_name: e.last_name, email: e.email, org_email: e.org_email ?? '', phone: e.phone, address: e.address ?? '', job_title: e.job_title, department_id: e.department_id, reports_to: e.reports_to, level: e.level, role: e.role, employment_type: e.employment_type, pay_frequency: e.pay_frequency, salary: e.salary, tax_rate: e.tax_rate, start_date: e.start_date, emergency_contact: e.emergency_contact, emergency_phone: e.emergency_phone, gender: e.gender ?? '', date_of_birth: e.date_of_birth ?? '', uan_no: e.uan_no ?? '', esi_no: e.esi_no ?? '', aadhaar_no: '', pan_no: e.pan_no ?? '' })
  const { can, isHrOrMaster: hrOnly } = useSession()
  const canManage = can('people.manage')
  // The reporting line runs up the levels: the same level or above, never below.
  const rank = (code: string) => cat.data?.levels.find((l) => l.code === code)?.rank ?? 0
  const managers = (people.data ?? []).filter((p) => p.id !== e.id && (!f.level || !p.level || rank(p.level) >= rank(f.level)))
  // Choosing a role fills in a level if there is none. A fixed role this person already holds stays in the list, since it cannot be handed to anyone else.
  const roleOptions = [...(cat.data?.roles ?? []), ...(e.role && !cat.data?.roles.some((r) => r.code === e.role) ? [{ code: e.role, label: e.role }] : [])]
  const pickRole = (code: string) => setF((s) => ({ ...s, role: code, level: s.level || cat.data?.roles.find((r) => r.code === code)?.level || '' }))
  const set = (k: keyof typeof f) => (ev: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: ev.target.value }))
  const qc = useQueryClient()
  // The server answers with the saved profile: shown at once, the lists refreshed behind it.
  // A changed salary is kept in the history as an increment, unless it only puts right a figure typed wrongly.
  const [correction, setCorrection] = useState(false)
  const salaryChanged = Number(f.salary || 0) !== Number(e.salary || 0)
  const body = { ...(f.aadhaar_no.trim() ? f : (({ aadhaar_no: _kept, ...rest }) => rest)(f)), salary_correction: salaryChanged && correction }
  const save = useAction(() => updateEmployee(e.id, body), { success: 'Saved', onSuccess: (r) => { showEmployeeChange(qc, { saved: r }); onDone() } })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <h4 className="col-span-full text-sm font-semibold">Personal details</h4>
        <Field label="First name" htmlFor="ep-first"><Input id="ep-first" value={f.first_name} onChange={set('first_name')} /></Field>
        <Field label="Last name" htmlFor="ep-last"><Input id="ep-last" value={f.last_name} onChange={set('last_name')} /></Field>
        <Field label="Gender" htmlFor="ep-gender"><Select id="ep-gender" value={f.gender} placeholder="Not given" onChange={set('gender')} options={GENDERS.map((g) => ({ value: g, label: g }))} /></Field>
        <Field label="Date of birth" htmlFor="ep-dob" hint="Colleagues see the day and month, for birthday wishes."><Input id="ep-dob" type="date" max={new Date().toISOString().slice(0, 10)} value={f.date_of_birth} onChange={set('date_of_birth')} /></Field>
        <Field label="Personal email" htmlFor="ep-email"><Input id="ep-email" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Phone" htmlFor="ep-phone"><Input id="ep-phone" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Address" htmlFor="ep-address" className="sm:col-span-2 lg:col-span-3"><Textarea id="ep-address" rows={2} value={f.address} onChange={(ev) => setF((s) => ({ ...s, address: ev.target.value }))} /></Field>
        {hrOnly && <Field label="UAN" htmlFor="ep-uan" hint="12 digits."><Input id="ep-uan" inputMode="numeric" value={f.uan_no} onChange={set('uan_no')} autoComplete="off" /></Field>}
        {hrOnly && <Field label="Aadhaar number" htmlFor="ep-aadhaar" hint={e.aadhaar_masked ? `On file: ${e.aadhaar_masked}. Leave blank to keep it.` : '12 digits.'}><Input id="ep-aadhaar" inputMode="numeric" value={f.aadhaar_no} onChange={set('aadhaar_no')} autoComplete="off" /></Field>}
        {hrOnly && <Field label="PAN number" htmlFor="ep-pan" hint="Like ABCDE1234F."><Input id="ep-pan" value={f.pan_no} onChange={(ev) => setF((s) => ({ ...s, pan_no: ev.target.value.toUpperCase() }))} autoComplete="off" /></Field>}
        {hrOnly && <Field label="ESI number" htmlFor="ep-esi" hint="10 digits."><Input id="ep-esi" inputMode="numeric" value={f.esi_no} onChange={set('esi_no')} autoComplete="off" /></Field>}
        <Field label="Emergency contact" htmlFor="ep-em"><Input id="ep-em" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Emergency phone" htmlFor="ep-emp"><Input id="ep-emp" value={f.emergency_phone} onChange={set('emergency_phone')} /></Field>
        <div className="col-span-full mt-1 border-t border-border pt-4"><h4 className="text-sm font-semibold">Company details</h4></div>
        <Field label="Organization email (Yahoo sign-in)" htmlFor="ep-org-email"><Input id="ep-org-email" type="email" value={f.org_email} onChange={set('org_email')} /></Field>
        <Field label="Job title" htmlFor="ep-title"><Input id="ep-title" value={f.job_title} onChange={set('job_title')} /></Field>
        <Field label="Department" htmlFor="ep-dept" hint={canManage ? undefined : 'Only the Master or HR moves people between departments.'}><Select id="ep-dept" disabled={!canManage} value={f.department_id ?? ''} onChange={(ev) => setF((s) => ({ ...s, department_id: ev.target.value ? Number(ev.target.value) : null }))} placeholder="None" options={(depts.data ?? []).filter((d) => d.site_ids.length > 0 || d.id === f.department_id).map((d) => ({ value: d.id, label: d.name }))} /></Field>
        <Field label="Reports to" htmlFor="ep-mgr" hint={canManage ? 'Follows the role; change it if needed.' : 'Set automatically from the role. Only the Master or HR can change it.'}><Select id="ep-mgr" disabled={!canManage} value={f.reports_to ?? ''} onChange={(ev) => setF((s) => ({ ...s, reports_to: ev.target.value ? Number(ev.target.value) : null }))} placeholder="None" options={managers.map((p) => ({ value: p.id, label: p.level ? `${p.full_name} (${p.level})` : p.full_name }))} /></Field>
        <Field label="Level" htmlFor="ep-level"><Select id="ep-level" value={f.level} onChange={set('level')} placeholder="Not set" options={(cat.data?.levels ?? []).map((l) => ({ value: l.code, label: l.label }))} /></Field>
        <Field label="Reporting role" htmlFor="ep-role"><Select id="ep-role" value={f.role} onChange={(ev) => pickRole(ev.target.value)} placeholder="Not set" options={roleOptions.map((r) => ({ value: r.code, label: r.label }))} /></Field>
        <Field label="Start date" htmlFor="ep-start"><Input id="ep-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Salary" htmlFor="ep-salary" hint={salaryChanged ? (correction ? 'Kept in the log only, not as an increment.' : 'Kept in the salary history as an increment from today.') : undefined}>
          <NumField id="ep-salary" value={f.salary} onValue={(n) => setF((s) => ({ ...s, salary: n }))} />
          {salaryChanged && (
            <label className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={correction} onChange={(ev) => setCorrection(ev.target.checked)} />
              This corrects a mistake, it is not an increment
            </label>
          )}
        </Field>
        <Field label="Tax rate %" htmlFor="ep-tax"><NumField id="ep-tax" value={f.tax_rate} onValue={(n) => setF((s) => ({ ...s, tax_rate: n }))} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        {canManage && <Button variant="outline" onClick={onPassword} disabled={!e.email} title={e.email ? undefined : 'Give them an email address first - they sign in with it'}>{e.has_password ? 'Change password' : 'Set password'}</Button>}
        <Button variant="outline" onClick={onDone}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
      </div>
    </div>
  )
}

/** Moves the employee between stages; the Master only. The status shown in the header follows. */
function StatusMenu({ e }: { e: EmployeeDetail }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [asking, setAsking] = useState<null | 'offboard' | 'terminate'>(null)
  // The screen follows the server's reply at once; the lists are read again behind it rather than ahead of it.
  const change = useAction((to: 'onboard' | 'offboard' | 'terminate') => setEmployeeStatus(e.id, to), {
    success: (r) => r.message,
    onSuccess: (r) => {
      setAsking(null)
      qc.setQueryData<EmployeeDetail>(['people', 'employee', e.id], (old) => old && { ...old, status: r.status, ...(r.end_date !== undefined && { end_date: r.end_date }) })
      qc.setQueriesData<{ id: number; status: string }[]>({ queryKey: ['people', 'employees'] }, (old) => Array.isArray(old) ? old.map((p) => (p.id === e.id ? { ...p, status: r.status } : p)) : old)
      void qc.invalidateQueries({ queryKey: ['people', 'employees'] })
      void qc.invalidateQueries({ queryKey: ['people', 'departments'] })
    },
  })
  // Gone from every list at once and back to the list straight away; the departments and counts are read again behind it.
  const del = useAction(() => deleteEmployee(e.id), {
    success: `${e.full_name} was deleted`,
    onSuccess: () => {
      navigate('/people/employees')
      showEmployeeChange(qc, { deletedId: e.id })
    },
    onError: () => setDeleting(false),
  })
  const pick = (fn: () => void) => () => { setOpen(false); fn() }
  const item = 'block w-full px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50'
  return (
    <div className="relative inline-block" onKeyDown={(ev) => ev.key === 'Escape' && setOpen(false)}>
      <Button variant="outline" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>Status <ChevronDown className="size-4" /></Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div role="menu" className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-card">
            <button role="menuitem" className={item} disabled={e.status === 'onboarding'} onClick={pick(() => change.mutate('onboard'))}>Onboard</button>
            <button role="menuitem" className={item} disabled={e.status === 'offboarding'} onClick={pick(() => setAsking('offboard'))}>Offboard</button>
            <button role="menuitem" className={`${item} text-danger`} disabled={e.status === 'terminated'} onClick={pick(() => setAsking('terminate'))}>Terminate</button>
            <button role="menuitem" className={`${item} text-danger`} onClick={pick(() => setDeleting(true))}>Delete</button>
          </div>
        </>
      )}
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={`Delete ${e.full_name}?`} description="Removes them for good, with their payslips, attendance, leave, documents and site assignments. This cannot be undone." confirmLabel="Delete for good" tone="danger" loading={del.isPending} onConfirm={() => del.mutate()} />
      <ConfirmDialog open={asking === 'offboard'} onOpenChange={(o) => !o && setAsking(null)} title={`Offboard ${e.full_name}?`} description="Their status becomes offboarding." confirmLabel="Offboard" tone="danger" loading={change.isPending} onConfirm={() => change.mutate('offboard')} />
      <ConfirmDialog open={asking === 'terminate'} onOpenChange={(o) => !o && setAsking(null)} title={`Terminate ${e.full_name}?`} description="Their status becomes terminated and today is recorded as their last day." confirmLabel="Terminate" tone="danger" loading={change.isPending} onConfirm={() => change.mutate('terminate')} />
    </div>
  )
}

export default function EmployeePage() {
  const qc = useQueryClient()
  const id = Number(useParams().id)
  const q = useEmployee(id)
  const [tab, setTab] = useState<Tab | null>(null)
  const e = q.data
  const { can } = useSession()
  const canManage = can('people.manage')
  const [givingPassword, setGivingPassword] = useState(false)
  // Drawn from their list row until the record arrives: the profile shows at once, editing waits for the real thing.
  const ready = !q.isPlaceholderData
  const shown: Tab = canManage && ready ? (tab ?? 'profile') : 'profile'
  if (q.isPending) return <Skeleton className="h-64 w-full" />
  if (!e) return <p role="alert" className="py-10 text-center text-sm text-danger">Could not open that employee.</p>
  return (
    <>
      <Link to="/people/employees" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Employees</Link>
      <PageHeader eyebrow={e.employee_id} title={e.full_name} description={[e.job_title, e.department_name, e.manager_name && `reports to ${e.manager_name}`].filter(Boolean).join(' · ') || undefined} actions={<Badge tone={EMPLOYEE_TONE[e.status] ?? 'neutral'}>{e.status}</Badge>} />
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <Tabs label="Section" value={shown} onChange={setTab} items={canManage && ready ? [{ value: 'profile', label: 'Profile' }, { value: 'access', label: 'Access' }] : [{ value: 'profile', label: 'Profile' }]} />
        {canManage && ready && <StatusMenu e={e} />}
      </div>
      {shown === 'profile' && <Profile key={e.id} e={e} ready={ready} onPassword={() => setGivingPassword(true)} />}
      {shown === 'access' && <EmployeeAccess key={e.id} e={e} />}
      {givingPassword && <SetPasswordModal who={e.full_name} email={e.email} hasPassword={e.has_password} save={async (password) => { const r = await setEmployeePassword(e.id, password); showEmployeeChange(qc, { patch: { id: e.id, has_password: true } }); return r }} invalidate={[]} onClose={() => setGivingPassword(false)} />}
    </>
  )
}
