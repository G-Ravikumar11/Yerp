import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { get, post, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { qcKeys } from '@/api/quality'
import { formatDate } from '@/lib/format'

interface DueTest { set_id: number; reference: string; project: string; grade: string; cast_on: string; due_on: string; status: string }
interface FailedTest { set_id: number; reference: string; project: string; grade: string; required: number; actual: number; ncr_id: number | null; ncr_number: string; ncr_status: string }
interface RejectedSet { set_id: number; reference: string; project: string; grade: string; reason: string; rejected_on: string }
interface Dash { due_today: DueTest[]; due_tomorrow: DueTest[]; failed: FailedTest[]; failed_total: number; rejected: RejectedSet[]; rejected_total: number; projects: { job_id: number; project: string; today: number; tomorrow: number }[] }
interface Notice { id: number; project: string; run_date: string; test_count: number; tests: { today?: DueTest[]; tomorrow?: DueTest[] }; status: string; sent_to: string; sent_at: string; error: string; attempts: number }

const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'
const td = 'px-3 py-2'
const TONE: Record<string, 'success' | 'danger' | 'warning' | 'info'> = { Sent: 'success', Failed: 'danger', Sending: 'warning', Pending: 'info' }

function Table({ label, head, rows, empty }: { label: string; head: string[]; rows: React.ReactNode[][]; empty: string }) {
  return (
    <section aria-label={label} className="min-w-0">
      <h3 className="mb-2 text-sm font-semibold">{label} ({rows.length})</h3>
      <div className="overflow-x-auto rounded-lg border border-border"><table aria-label={label} className="w-full min-w-[34rem] text-[13px]">
        <thead className="bg-surface"><tr>{head.map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
        <tbody>{rows.length ? rows.map((r, i) => <tr key={i} className="border-t border-border align-top">{r.map((c, j) => <td key={j} className={td}>{c}</td>)}</tr>) : <tr><td colSpan={head.length} className="px-3 py-4 text-center text-muted-foreground">{empty}</td></tr>}</tbody>
      </table></div>
    </section>
  )
}

/** What is due today and tomorrow, what failed and its NCR, and what was rejected: the same reading the daily notice uses. */
export function CubeDashboard({ job, onNcr }: { job: number; onNcr: (id: number) => void }) {
  const { can } = useSession()
  const [f, setF] = useState({ q: '', grade: '', ncr_status: '', due_from: '', due_to: '' })
  const [notices, setNotices] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const qs = new URLSearchParams({ job_id: String(job || 0), ...f }).toString()
  const q = useQuery({ queryKey: [...qcKeys.all, 'cube-dashboard', qs], staleTime: 0, refetchOnMount: 'always', queryFn: () => get<Dash>(`/api/qc/cube-dashboard?${qs}`) })
  const d = q.data
  const dueRow = (t: DueTest) => [t.reference, t.project, t.grade, formatDate(t.cast_on), formatDate(t.due_on), t.status]
  const dueHead = ['Test', 'Project', 'Grade', 'Cast', 'Due', 'Status']
  return (
    <section aria-label="Cube test dashboard" className="mb-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-44"><Input aria-label="Search cube tests" placeholder="Reference" value={f.q} onChange={set('q')} /></div>
        <div className="w-28"><Input aria-label="Grade" placeholder="Grade" value={f.grade} onChange={set('grade')} /></div>
        <div className="w-36"><Select aria-label="NCR status" value={f.ncr_status} placeholder="Any NCR" onChange={set('ncr_status')} options={['OPEN', 'CLOSED'].map((x) => ({ value: x, label: x === 'OPEN' ? 'Open' : 'Closed' }))} /></div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Due from<Input type="date" aria-label="Due from" className="w-36" value={f.due_from} onChange={set('due_from')} /></label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">to<Input type="date" aria-label="Due to" className="w-36" value={f.due_to} onChange={set('due_to')} /></label>
        {can('site.record|site.signoff') && <Button className="ml-auto" variant="outline" onClick={() => setNotices(true)}>Notices</Button>}
      </div>
      {q.isError ? <p role="alert" className="text-sm text-danger">{q.error.message}</p> : q.isPending || !d ? <Skeleton className="h-32 w-full" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Table label="Due today" head={dueHead} rows={d.due_today.map(dueRow)} empty="Nothing due today." />
          <Table label="Due tomorrow" head={dueHead} rows={d.due_tomorrow.map(dueRow)} empty="Nothing due tomorrow." />
          <Table label="Failed tests" head={['Test', 'Project', 'Required', 'Actual', 'NCR', 'NCR status']} empty="No failed tests." rows={d.failed.map((t) => [t.reference, t.project, t.required, t.actual, t.ncr_id ? <button key="n" type="button" className="font-medium text-primary hover:underline" onClick={() => onNcr(t.ncr_id!)}>{t.ncr_number}</button> : '-', t.ncr_status ? <Badge key="s" tone={t.ncr_status === 'CLOSED' ? 'success' : 'danger'} dot>{t.ncr_status === 'CLOSED' ? 'Closed' : 'Open'}</Badge> : '-'])} />
          <Table label="Rejected test sets" head={['Set', 'Project', 'Reason', 'Rejected']} empty="No rejected sets." rows={d.rejected.map((t) => [t.reference, t.project, t.reason || '-', t.rejected_on ? formatDate(t.rejected_on) : '-'])} />
        </div>
      )}
      {notices && <NoticesModal job={job} onClose={() => setNotices(false)} />}
    </section>
  )
}

function NoticesModal({ job, onClose }: { job: number; onClose: () => void }) {
  const { can } = useSession()
  const q = useQuery({ queryKey: [...qcKeys.all, 'cube-notices', job], queryFn: () => get<{ notices: Notice[]; total: number }>(`/api/qc/cube-notices?job_id=${job || 0}`) })
  const s = useQuery({ queryKey: [...qcKeys.all, 'cube-notice-settings', job], queryFn: () => get<{ hour: number; timezone: string; default_timezone: string; emails: string }>(`/api/qc/cube-notices/settings?job_id=${job || 0}`) })
  const [v, setV] = useState<{ hour?: string; timezone?: string; emails?: string }>({})
  const hour = v.hour ?? String(s.data?.hour ?? '')
  const tz = v.timezone ?? s.data?.timezone ?? ''
  const emails = v.emails ?? s.data?.emails ?? ''
  const retry = useAction((id: number) => post<{ message: string }>(`/api/qc/cube-notices/${id}/retry`), { invalidate: [qcKeys.all], success: (r) => r.message })
  const save = useAction(() => put<{ message: string }>('/api/qc/cube-notices/settings', { hour: Number(hour), job_id: job || 0, timezone: tz, emails }), { invalidate: [qcKeys.all], success: (r) => r.message })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="Cube test notices" description="One notice a day for each project with tests due today or tomorrow." footer={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      {can('site.signoff') && (
        <div className="mb-4 grid gap-3 rounded-lg border border-border p-3 sm:grid-cols-3">
          <Field label="Send at (hour, 0-23)" htmlFor="cn-h"><Input id="cn-h" type="number" min="0" max="23" value={hour} onChange={(e) => setV((x) => ({ ...x, hour: e.target.value }))} /></Field>
          {job > 0 && <Field label="Project time zone" htmlFor="cn-tz" hint={`Blank: ${s.data?.default_timezone ?? ''}`}><Input id="cn-tz" value={tz} onChange={(e) => setV((x) => ({ ...x, timezone: e.target.value }))} /></Field>}
          {job > 0 && <Field label="Project recipients" htmlFor="cn-em" hint="Emails, separated by commas"><Input id="cn-em" value={emails} onChange={(e) => setV((x) => ({ ...x, emails: e.target.value }))} /></Field>}
          <div className="flex items-center justify-end gap-2 sm:col-span-3">{!job && <span className="mr-auto text-xs text-muted-foreground">Choose a project for its time zone and recipients.</span>}<Button size="sm" variant="outline" loading={save.isPending} disabled={save.isPending} onClick={() => save.mutate()}>Save settings</Button></div>
          {save.error && <p role="alert" className="text-[13px] text-danger sm:col-span-3">{save.error.message}</p>}
        </div>
      )}
      {q.isPending ? <Skeleton className="h-24 w-full" /> : q.isError ? <p role="alert" className="text-sm text-danger">{q.error.message}</p> : (
        <div className="overflow-x-auto rounded-lg border border-border"><table aria-label="Notice history" className="w-full min-w-[40rem] text-[13px]">
          <thead className="bg-surface"><tr>{['Project', 'Date', 'Tests', 'References', 'Status', 'Sent', ''].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>{q.data.notices.length ? q.data.notices.map((n) => (
            <tr key={n.id} className="border-t border-border align-top">
              <td className={td}>{n.project}</td><td className={td}>{formatDate(n.run_date)}</td><td className={td}>{n.test_count}</td>
              <td className={td}>{[...(n.tests.today ?? []), ...(n.tests.tomorrow ?? [])].map((t) => t.reference).join(', ')}</td>
              <td className={td}><Badge tone={TONE[n.status] ?? 'info'} dot>{n.status}</Badge>{n.error && <div className="text-xs text-danger">{n.error}</div>}</td>
              <td className={td}>{n.sent_at || '-'}<div className="text-xs text-muted-foreground">{n.sent_to}</div></td>
              <td className={td}>
                {can('site.signoff') && (
                  <Button size="sm" variant="outline" loading={retry.isPending} disabled={retry.isPending} title="Email this notice to the project's addresses that have not had it" onClick={() => retry.mutate(n.id)}>
                    {n.status === 'Failed' ? 'Retry' : 'Send email'}
                  </Button>
                )}
              </td>
            </tr>
          )) : <tr><td colSpan={7} className="px-3 py-4 text-center text-muted-foreground">No notices yet.</td></tr>}</tbody>
        </table></div>
      )}
    </Modal>
  )
}

