import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { ID_DOCUMENTS, createEmployee, sendCredentialsEmail, saveDepartment, peopleKeys, uploadEmployeeDocument, useDepartments, useEmployees, useHrCatalogue, useSuggestedEmail, type EmployeeInput, type IdDocumentKey } from '@/api/people'
import { useJobOptions } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { useSession } from '@/lib/session'
import { useDebounced } from '@/lib/hooks'
import { AccessPicker } from './AccessPicker'
import { DocumentPick } from './EmployeeDocuments'
import { DEPARTMENT_COLORS } from './icons'
import { PayrollFields } from './PayrollFields'
import { PasswordField, passwordProblem } from '@/features/auth/PasswordField'

export const GENDERS = ['Male', 'Female', 'Other', 'Prefer not to say']

const blank = (): EmployeeInput => ({ first_name: '', last_name: '', email: '', org_email: '', password: '', phone: '', job_title: '', department_id: null, reports_to: null, level: '', role: '', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 0, tax_rate: 0, start_date: today(), emergency_contact: '', emergency_phone: '', aadhaar_no: '', pan_no: '', uan_no: '', esi_no: '', bank_name: '', bank_account: '', bank_ifsc: '', pf_enabled: true, esi_enabled: true, pt_enabled: true, pt_state: 'TS', probation_end_date: '', contract_end_date: '' })

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
  const [confirm, setConfirm] = useState('')
  // Step 1 is who they are and what they do here; step 2 is where they work and what they may do. Nothing is saved until the end.
  const [step, setStep] = useState<1 | 2>(1)
  // The Aadhaar, PAN and ESI cards chosen here are kept on the employee's record once they are created.
  const [files, setFiles] = useState<Partial<Record<IdDocumentKey, File>>>({})
  // A card's upload option appears once its number is clicked, and stays.
  const [shown, setShown] = useState<Partial<Record<IdDocumentKey, boolean>>>({})
  const reveal = (key: IdDocumentKey) => () => setShown((s) => (s[key] ? s : { ...s, [key]: true }))
  const pickFile = (key: IdDocumentKey) => (file: File | null) => setFiles((s) => { const { [key]: _gone, ...rest } = s; return file ? { ...rest, [key]: file } : rest })
  const [given, setGiven] = useState<{ dbId: number; id: string; email: string; password: string; sites: string; notKept: string[] } | null>(null)
  const cat = useHrCatalogue()
  const { can, isHrOrMaster: hrOnly } = useSession()
  const canManage = can('people.manage')
  const depts = useDepartments()
  // HR types the department. A name that matches one already set up joins it; a new name is made into a department on save.
  const [deptName, setDeptName] = useState('')
  const people = useEmployees('')
  const jobs = useJobOptions(false)
  // Not on every letter: the address is asked for once the name has stopped changing.
  const suggested = useSuggestedEmail(useDebounced(f.first_name, 400), useDebounced(f.last_name, 400))
  const set = (k: keyof EmployeeInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  // The reporting line runs up the levels: somebody can report to the same level or above, never below. People with no level yet are not ruled out.
  const rank = (code: string) => cat.data?.levels.find((l) => l.code === code)?.rank ?? 0
  // Everybody, senior first: the Master decides who reports to whom (a coordinator between a site and the heads, say).
  const managers = [...(people.data ?? [])].sort((a, b) => rank(b.level ?? '') - rank(a.level ?? '') || a.full_name.localeCompare(b.full_name))
  // Choosing a role fills in its level. The reporting line follows the role too: the Master sees who it will be and may pick somebody else; for everyone else the server sets it when the employee is saved.
  // Access follows the role and the level, so the Master does not tick it all again: the access level the role carries is
  // chosen and its rights ticked at once, and can still be changed below. Only the Master gives access; for anybody else the server's default stands.
  const giveAccess = (access?: string) => {
    const level = canManage && access ? cat.data?.permission_roles.find((x) => x.code === access) : undefined
    if (!level) return
    setF((s) => ({ ...s, permission_role: level.code }))
    setGranted(level.permissions)
  }
  const pickRole = (code: string) => {
    const r = cat.data?.roles.find((x) => x.code === code)
    setF((s) => {
      const boss = canManage && r?.reports_to ? (people.data ?? []).find((p) => p.role === r.reports_to) : undefined
      return { ...s, role: code, level: r?.level || s.level, reports_to: boss?.id ?? s.reports_to }
    })
    giveAccess(r?.access)
  }
  // A level on its own gives access too: the level is named for its main role ("L5 - Project Manager", "L8 - Site Engineer"),
  // so that role's access is used; the role can then be chosen to refine it. Where no role fits the name, an access every
  // role at the level shares is used, and otherwise nothing is guessed.
  const pickLevel = (level: string) => {
    const here = (cat.data?.roles ?? []).filter((r) => r.level === level)
    setF((s) => ({ ...s, level, role: here.some((r) => r.code === s.role) ? s.role : '' }))
    const name = (cat.data?.levels.find((l) => l.code === level)?.label ?? '').toLowerCase()
    const main = here.find((r) => name.includes(r.label.toLowerCase()))
    const shared = [...new Set(here.map((r) => r.access).filter(Boolean))]
    giveAccess(main?.access ?? (shared.length === 1 ? shared[0] : undefined))
  }
  const num = (k: keyof EmployeeInput) => (n: number) => setF((s) => ({ ...s, [k]: n }))
  // Their own address follows their name until somebody types one.
  const [typed, setTyped] = useState(false)
  useEffect(() => { if (!typed && suggested.data) setF((s) => ({ ...s, email: suggested.data })) }, [suggested.data, typed])
  useEffect(() => { const r = cat.data?.permission_roles.find((x) => x.code === f.permission_role); if (r && granted.length === 0) setGranted(r.permissions) }, [cat.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const qc = useQueryClient()
  // One request: the access the Master ticked is saved with the employee. The People lists then
  // refresh behind the details screen rather than holding it until every one has reloaded.
  const save = useAction(async () => {
    const typedDept = deptName.trim().replace(/\s+/g, ' ')
    let department_id: number | null = null
    if (typedDept) {
      const known = (depts.data ?? []).find((d) => d.name.trim().toLowerCase() === typedDept.toLowerCase())
      if (known) department_id = known.id
      else {
        department_id = (await saveDepartment(null, { name: typedDept, description: '', color: DEPARTMENT_COLORS[0], icon: 'building' })).id
        await depts.refetch()   // so a retry after a failed save finds it instead of making it twice
      }
    }
    const r = await createEmployee({ ...f, department_id, password: f.permission_role === 'attendance' ? '' : f.password?.trim(), ...(canManage ? { permissions: granted } : {}) })
    // The employee exists now, so the cards can be kept on their record. One that cannot be does not undo the rest.
    const notKept: string[] = []
    for (const d of ID_DOCUMENTS) {
      const file = files[d.key]
      if (!file) continue
      try { await uploadEmployeeDocument(r.id, d.title, d.type, file) } catch { notKept.push(d.title) }
    }
    return { ...r, notKept }
  }, {
    success: (r) => r.message || 'Employee created',
    onSuccess: (r) => {
      setGiven({ dbId: r.id, id: r.employee_id, email: f.permission_role === 'attendance' ? '' : f.email, password: f.permission_role === 'attendance' ? '' : f.password ?? '', sites: (r.site_names ?? []).join(', ') || 'Every site', notKept: r.notKept })
      void qc.invalidateQueries({ queryKey: peopleKeys.all })
    },
  })
  const pass = f.password?.trim() ?? ''
  // A login needs an email, a password that passes the rule, and the same password typed twice. Staff who never sign in need none of it.
  const passError = pass ? passwordProblem(pass) : ''
  const confirmError = pass && confirm !== pass ? 'Those two do not match.' : ''
  // The one thing every new starter must have: somebody to call in an emergency, by name and number.
  const emergencyOk = f.emergency_contact.trim() !== '' && f.emergency_phone.replace(/\D/g, '').length >= 7
  const digitsBad = (v: string | null | undefined, n: number) => !!v && !(/^\d+$/.test(v.replace(/\s/g, '')) && v.replace(/\s/g, '').length === n)
  const ready = f.first_name.trim() && f.last_name.trim() && !!f.gender && emergencyOk && (!pass || (f.email.trim() && !passError && !confirmError))

  const mailTo = f.email.trim() || (f.org_email ?? '').trim()
  // Send email: the details below go to the employee's own email, from the company's HR department.
  const mailDetails = useAction(async () => {
    const r = await sendCredentialsEmail(given!.dbId, given!.password)
    if (!r.ok) throw new Error(r.message)
    return r
  }, { success: (r) => r.message })

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
        {given.notKept.length > 0 && <p role="alert" className="mt-3 text-sm text-danger">The employee was created, but these could not be attached: {given.notKept.join(', ')}. Add them from the employee's page.</p>}
        <p className="mt-3 text-xs text-muted-foreground">The password is stored hashed and cannot be shown again. If it is lost, set a new one from their record (Set password).</p>
        <div className="mt-4 flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Done</Button>{given.password && mailTo && <Button loading={mailDetails.isPending} disabled={mailDetails.isSuccess} onClick={() => mailDetails.mutate()} title={`Send these details to ${mailTo} from HR`}>{mailDetails.isSuccess ? 'Email sent' : 'Send email'}</Button>}</div>
      </div>
    )

  const stepLabel = (n: 1 | 2, text: string) => (
    <li aria-current={step === n ? 'step' : undefined} className={'flex items-center gap-2 ' + (step === n ? 'font-semibold text-foreground' : 'text-muted-foreground')}>
      <span className={'grid size-6 place-items-center rounded-full text-xs ' + (step === n ? 'bg-[var(--primary)] text-white' : 'border border-border')}>{n}</span>{text}
    </li>
  )
  return (
    <div>
      <ol aria-label="Steps" className="mb-5 flex items-center gap-3 text-sm">
        {stepLabel(1, 'Details')}
        <li aria-hidden className="h-px flex-1 bg-border" />
        {stepLabel(2, 'Sites and access')}
      </ol>
      <div hidden={step !== 1}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <h4 className="col-span-full text-sm font-semibold">Personal details</h4>
        <Field label="First name *" htmlFor="ef-first"><Input id="ef-first" value={f.first_name} onChange={set('first_name')} autoFocus /></Field>
        <Field label="Last name *" htmlFor="ef-last"><Input id="ef-last" value={f.last_name} onChange={set('last_name')} /></Field>
        <Field label="Gender *" htmlFor="ef-gender"><Select id="ef-gender" value={f.gender ?? ''} placeholder="Choose" onChange={set('gender')} options={GENDERS.map((g) => ({ value: g, label: g }))} /></Field>
        <Field label="Date of birth" htmlFor="ef-dob" hint="Optional. Colleagues are told on the day."><Input id="ef-dob" type="date" max={new Date().toISOString().slice(0, 10)} value={f.date_of_birth ?? ''} onChange={set('date_of_birth')} /></Field>
        <Field label="Phone" htmlFor="ef-phone"><Input id="ef-phone" type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label={pass ? 'Personal email *' : 'Personal email'} htmlFor="ef-email" error={f.email.trim() && !/^\S+@\S+\.\S+$/.test(f.email.trim()) ? 'Enter a valid email.' : undefined}><Input id="ef-email" type="email" autoComplete="off" value={f.email} onChange={(e) => { setTyped(true); set('email')(e) }} /></Field>
        <Field label="Address" htmlFor="ef-address" className="sm:col-span-2 lg:col-span-3"><Textarea id="ef-address" rows={2} value={f.address ?? ''} onChange={(e) => setF((s) => ({ ...s, address: e.target.value }))} /></Field>
        {hrOnly && <Field label="Aadhaar number" htmlFor="ef-aadhaar" hint="Optional." error={digitsBad(f.aadhaar_no, 12) ? 'Aadhaar is 12 digits.' : undefined}><Input id="ef-aadhaar" inputMode="numeric" value={f.aadhaar_no ?? ''} onChange={set('aadhaar_no')} onFocus={reveal('aadhaar')} onClick={reveal('aadhaar')} autoComplete="off" /><DocumentPick label="Aadhaar card" file={files.aadhaar ?? null} shown={!!shown.aadhaar} onFile={pickFile('aadhaar')} /></Field>}
        {hrOnly && <Field label="PAN number" htmlFor="ef-pan" hint="Optional." error={f.pan_no && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(f.pan_no.trim()) ? 'PAN looks like ABCDE1234F.' : undefined}><Input id="ef-pan" value={f.pan_no ?? ''} onChange={(e) => setF((s) => ({ ...s, pan_no: e.target.value.toUpperCase() }))} onFocus={reveal('pan')} onClick={reveal('pan')} autoComplete="off" /><DocumentPick label="PAN card" file={files.pan ?? null} shown={!!shown.pan} onFile={pickFile('pan')} /></Field>}
        <Field label="Emergency contact name *" htmlFor="ef-em"><Input id="ef-em" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Emergency contact phone *" htmlFor="ef-emp" error={f.emergency_phone && f.emergency_phone.replace(/\D/g, '').length < 7 ? 'Enter a phone number of at least 7 digits.' : undefined}><Input id="ef-emp" type="tel" value={f.emergency_phone} onChange={set('emergency_phone')} /></Field>
        <div className="col-span-full mt-1 border-t border-border pt-4"><h4 className="text-sm font-semibold">Company details</h4></div>
        <Field label="Employee ID" htmlFor="ef-eid"><Input id="ef-eid" value={f.employee_id ?? ''} onChange={set('employee_id')} /></Field>
        <Field label="Organization email (Yahoo sign-in)" htmlFor="ef-org-email"><Input id="ef-org-email" type="email" autoComplete="off" value={f.org_email ?? ''} onChange={set('org_email')} /></Field>
        <PasswordField id="ef-pass" label="Password" value={f.password ?? ''} onChange={(v) => setF((s) => ({ ...s, password: v }))} error={pass && passError ? passError : undefined} />
        {pass && <PasswordField id="ef-pass2" label="Confirm password *" value={confirm} onChange={setConfirm} error={confirm ? confirmError || undefined : undefined} placeholder="Type it again" />}
        <Field label="Job title" htmlFor="ef-title"><Input id="ef-title" value={f.job_title} onChange={set('job_title')} /></Field>
        <Field label="Level" htmlFor="ef-level"><Select id="ef-level" value={f.level} onChange={(e) => pickLevel(e.target.value)} placeholder="Not set" options={(cat.data?.levels ?? []).map((l) => ({ value: l.code, label: l.label }))} /></Field>
        <Field label="Department" htmlFor="ef-dept"><Input id="ef-dept" disabled={!canManage} value={deptName} onChange={(e) => setDeptName(e.target.value)} placeholder="e.g. Civil" autoComplete="off" /></Field>
        <Field label="Reports to" htmlFor="ef-mgr"><Select id="ef-mgr" disabled={!canManage} value={f.reports_to ?? ''} onChange={(e) => setF((s) => ({ ...s, reports_to: e.target.value ? Number(e.target.value) : null }))} placeholder="The Master" options={managers.map((p) => ({ value: p.id, label: p.level ? `${p.full_name} (${p.level})` : p.full_name }))} /></Field>
        <Field label="Reporting role" htmlFor="ef-role"><Select id="ef-role" value={f.role} onChange={(e) => pickRole(e.target.value)} placeholder="Not set" options={(cat.data?.roles ?? []).filter((r) => !f.level || r.level === f.level).map((r) => ({ value: r.code, label: r.label }))} /></Field>
        <Field label="Start date" htmlFor="ef-start"><Input id="ef-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Type" htmlFor="ef-type"><Select id="ef-type" value={f.employment_type} onChange={set('employment_type')} options={[['full_time', 'Full time'], ['part_time', 'Part time'], ['contract', 'Contract'], ['intern', 'Intern']].map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Paid" htmlFor="ef-freq"><Select id="ef-freq" value={f.pay_frequency} onChange={set('pay_frequency')} options={[['monthly', 'Monthly'], ['biweekly', 'Every two weeks'], ['weekly', 'Weekly'], ['hourly', 'Hourly']].map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Salary" htmlFor="ef-salary"><NumField id="ef-salary" value={f.salary} onValue={num('salary')} /></Field>
        <Field label="Tax rate %" htmlFor="ef-tax"><NumField id="ef-tax" value={f.tax_rate} onValue={num('tax_rate')} /></Field>
        {hrOnly && <Field label="UAN" htmlFor="ef-uan" hint="Optional." error={digitsBad(f.uan_no, 12) ? 'UAN is 12 digits.' : undefined}><Input id="ef-uan" inputMode="numeric" value={f.uan_no ?? ''} onChange={set('uan_no')} autoComplete="off" /></Field>}
        {hrOnly && <Field label="ESI number" htmlFor="ef-esi" hint="Optional." error={digitsBad(f.esi_no, 10) ? 'ESI number is 10 digits.' : undefined}><Input id="ef-esi" inputMode="numeric" value={f.esi_no ?? ''} onChange={set('esi_no')} onFocus={reveal('esi')} onClick={reveal('esi')} autoComplete="off" /><DocumentPick label="ESI card" file={files.esi ?? null} shown={!!shown.esi} onFile={pickFile('esi')} /></Field>}
        {hrOnly && <PayrollFields id="ef" value={f} onChange={(patch) => setF((s) => ({ ...s, ...patch }))} />}
      </div>
      </div>
      <div hidden={step !== 2}>
        <div className="grid gap-4">
          <Field label="Sites" htmlFor="ef-sites">
            <div className="flex flex-col gap-y-1.5" id="ef-sites">
              {(jobs.data ?? []).map((j) => <label key={j.id} className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="size-4 accent-[var(--primary)]" checked={f.site_ids.includes(j.id)} onChange={(e) => setF((s) => ({ ...s, site_ids: e.target.checked ? [...s.site_ids, j.id] : s.site_ids.filter((x) => x !== j.id) }))} />{j.number} {j.name}</label>)}
            </div>
          </Field>
        </div>
      {canManage && cat.data && <div className="mt-5"><AccessPicker catalogue={cat.data} role={f.permission_role} granted={granted} onRole={(code, rights) => { setF((s) => ({ ...s, permission_role: code, ...(code === 'attendance' ? { password: '' } : {}) })); if (code === 'attendance') setConfirm(''); setGranted(rights) }} onGranted={setGranted} />{f.permission_role === 'attendance' && <p className="mt-2 text-[13px] text-muted-foreground">Attendance only: no sign-in and no access. Their attendance and salary are still kept.</p>}</div>}
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {step === 2 && save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        {step === 1 ? (
          <Button disabled={!ready} onClick={() => setStep(2)}>Save and continue</Button>
        ) : (
          <>
            <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
            <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Create the employee</Button>
          </>
        )}
      </div>
    </div>
  )
}
