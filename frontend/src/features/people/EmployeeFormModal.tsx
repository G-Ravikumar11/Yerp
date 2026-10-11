import { useEffect, useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { createEmployee, peopleKeys, setAccess, useDepartments, useEmployees, useHrCatalogue, useSuggestedEmail, type EmployeeInput } from '@/api/people'
import { useJobOptions } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { AccessPicker } from './AccessPicker'

const blank = (): EmployeeInput => ({ first_name: '', last_name: '', email: '', password: '', phone: '', job_title: '', department_id: null, reports_to: null, level: '', role: 'employee', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 0, tax_rate: 0, start_date: today(), emergency_contact: '', emergency_phone: '' })

/** A new member of staff: who they are, the department they belong to, what they may do, and a login if they need one. */
export function EmployeeFormModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title="Add an employee" description="Departments and access levels are the ones you have set up. Staff see their department and only the screens their access allows.">
      {open && <Form onClose={onClose} />}
    </Modal>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState<EmployeeInput>(blank)
  const [granted, setGranted] = useState<string[]>([])
  const [given, setGiven] = useState<{ id: string; email: string; password: string; sites: string } | null>(null)
  const cat = useHrCatalogue()
  const depts = useDepartments()
  const people = useEmployees('')
  const jobs = useJobOptions(false)
  const suggested = useSuggestedEmail(f.first_name, f.last_name)
  const set = (k: keyof EmployeeInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const num = (k: keyof EmployeeInput) => (n: number) => setF((s) => ({ ...s, [k]: n }))
  // Their own address follows their name until somebody types one.
  const [typed, setTyped] = useState(false)
  useEffect(() => { if (!typed && suggested.data) setF((s) => ({ ...s, email: suggested.data })) }, [suggested.data, typed])
  useEffect(() => { const r = cat.data?.permission_roles.find((x) => x.code === f.permission_role); if (r && granted.length === 0) setGranted(r.permissions) }, [cat.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useAction(async () => {
    const made = await createEmployee({ ...f, password: f.password?.trim() })
    await setAccess(made.id, { permission_role: f.permission_role, permissions: granted })
    return made
  }, { invalidate: [peopleKeys.all], success: (r) => r.message || 'Employee created', onSuccess: (r) => setGiven({ id: r.employee_id, email: f.email, password: f.password ?? '', sites: (r.site_names ?? []).join(', ') || 'Every site' }) })
  const ready = f.first_name.trim() && f.last_name.trim() && (!f.password?.trim() || f.email.trim())

  if (given)
    return (
      <div>
        <h3 className="mb-3 font-semibold">Give these to {f.first_name}</h3>
        <dl className="grid grid-cols-[8rem_1fr] gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Employee ID</dt><dd className="font-semibold">{given.id}</dd>
          <dt className="text-muted-foreground">Sign in with</dt><dd className="font-semibold">{given.email || '(no login)'}</dd>
          <dt className="text-muted-foreground">Password</dt><dd className="font-semibold">{given.password || '(no login)'}</dd>
          <dt className="text-muted-foreground">Sites</dt><dd>{given.sites}</dd>
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">The password is stored hashed and cannot be shown again. If it is lost, reset it from their profile.</p>
        <div className="mt-4 flex justify-end"><Button onClick={onClose}>Done</Button></div>
      </div>
    )

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="First name *" htmlFor="ef-first"><Input id="ef-first" value={f.first_name} onChange={set('first_name')} autoFocus /></Field>
        <Field label="Last name *" htmlFor="ef-last"><Input id="ef-last" value={f.last_name} onChange={set('last_name')} /></Field>
        <Field label="Employee ID" htmlFor="ef-eid" hint="Leave blank to number it."><Input id="ef-eid" value={f.employee_id ?? ''} onChange={set('employee_id')} /></Field>
        <Field label="Email (their login)" htmlFor="ef-email"><Input id="ef-email" type="email" value={f.email} onChange={(e) => { setTyped(true); set('email')(e) }} /></Field>
        <Field label="Password" htmlFor="ef-pass" hint="Leave blank for site staff who are paid without signing in."><Input id="ef-pass" type="text" autoComplete="off" value={f.password ?? ''} onChange={set('password')} /></Field>
        <Field label="Phone" htmlFor="ef-phone"><Input id="ef-phone" type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Job title" htmlFor="ef-title"><Input id="ef-title" value={f.job_title} onChange={set('job_title')} /></Field>
        <Field label="Department" htmlFor="ef-dept"><Select id="ef-dept" value={f.department_id ?? ''} onChange={(e) => setF((s) => ({ ...s, department_id: e.target.value ? Number(e.target.value) : null }))} placeholder="None" options={(depts.data ?? []).map((d) => ({ value: d.id, label: d.name }))} /></Field>
        <Field label="Reports to" htmlFor="ef-mgr"><Select id="ef-mgr" value={f.reports_to ?? ''} onChange={(e) => setF((s) => ({ ...s, reports_to: e.target.value ? Number(e.target.value) : null }))} placeholder="None" options={(people.data ?? []).map((p) => ({ value: p.id, label: p.full_name }))} /></Field>
        <Field label="Level" htmlFor="ef-level"><Select id="ef-level" value={f.level} onChange={set('level')} placeholder="Not set" options={(cat.data?.levels ?? []).map((l) => ({ value: l.code, label: l.label }))} /></Field>
        <Field label="Reporting role" htmlFor="ef-role"><Select id="ef-role" value={f.role} onChange={set('role')} options={(cat.data?.roles ?? [{ code: 'employee', label: 'Employee' }]).map((r) => ({ value: r.code, label: r.label }))} /></Field>
        <Field label="Start date" htmlFor="ef-start"><Input id="ef-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Type" htmlFor="ef-type"><Select id="ef-type" value={f.employment_type} onChange={set('employment_type')} options={[['full_time', 'Full time'], ['part_time', 'Part time'], ['contract', 'Contract'], ['intern', 'Intern']].map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Paid" htmlFor="ef-freq"><Select id="ef-freq" value={f.pay_frequency} onChange={set('pay_frequency')} options={[['monthly', 'Monthly'], ['biweekly', 'Every two weeks'], ['weekly', 'Weekly'], ['hourly', 'Hourly']].map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Salary" htmlFor="ef-salary"><NumField id="ef-salary" value={f.salary} onValue={num('salary')} /></Field>
        <Field label="Tax rate %" htmlFor="ef-tax"><NumField id="ef-tax" value={f.tax_rate} onValue={num('tax_rate')} /></Field>
        <Field label="Emergency contact" htmlFor="ef-em"><Input id="ef-em" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Sites" htmlFor="ef-sites" hint="None ticked means every site." className="sm:col-span-2 lg:col-span-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1" id="ef-sites">
            {(jobs.data ?? []).map((j) => <label key={j.id} className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="size-4 accent-[var(--primary)]" checked={f.site_ids.includes(j.id)} onChange={(e) => setF((s) => ({ ...s, site_ids: e.target.checked ? [...s.site_ids, j.id] : s.site_ids.filter((x) => x !== j.id) }))} />{j.number} {j.name}</label>)}
          </div>
        </Field>
      </div>
      {cat.data && <div className="mt-5"><AccessPicker catalogue={cat.data} role={f.permission_role} granted={granted} onRole={(code, rights) => { setF((s) => ({ ...s, permission_role: code })); setGranted(rights) }} onGranted={setGranted} /></div>}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Create the employee</Button>
      </div>
    </div>
  )
}
