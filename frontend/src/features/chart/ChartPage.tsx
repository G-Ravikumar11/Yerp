import { useMemo, useState } from 'react'
import { AlertTriangle, Flag, Pencil, Plus, Printer, Search, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, ConfirmDialog, Input, Select, Skeleton, Stat, StatGrid, Tabs } from '@/components/ui'
import { deleteActivity, schKeys, setProgress, useSchedule, type Activity } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { ActivityModal } from '@/features/schedule/ActivityModal'
import { BoqPickerModal } from '@/features/schedule/programme/BoqPickerModal'
import { ProgressBar } from '@/features/schedule/ProgressBar'
import { ProgressControl } from '@/features/schedule/ProgressControl'
import { Curve } from '@/features/schedule/Bars'
import { Gantt } from './Gantt'
import { LogoPrintModal, PrintReport, printChart } from './PrintReport'
import { useIdentity } from '@/api/identity'

type Tab = 'gantt' | 'list' | 'milestones'
const BAR = { done: 'bg-success', late: 'bg-danger', behind: 'bg-warning', 'on track': 'bg-primary', 'not started': 'bg-subtle' } as const
const STATUS = [
  { value: 'Not Started', label: 'Not Started' }, { value: 'In Progress', label: 'In Progress' }, { value: 'Completed', label: 'Completed' },
  { value: 'Delayed', label: 'Delayed' }, { value: 'overdue', label: 'Overdue (past deadline)' },
]
const STATUS_TONE = { 'Not Started': 'neutral', 'In Progress': 'info', Completed: 'success', Delayed: 'danger' } as const
const statusOf = (a: Activity) => (a.status || 'Not Started') as keyof typeof STATUS_TONE

/** The project chart: the programme on a timeline, who is to do what by when, how far along it is, and what is running late. */
export default function ChartPage() {
  const { can } = useSession()
  const manage = can('workorders.manage')
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<Tab>('gantt')
  const [f, setF] = useState({ q: '', status: '', who: '', from: '', to: '', milestones: false })
  const q = useSchedule(job)
  const d = q.data
  const s = d?.summary
  const [editing, setEditing] = useState<Activity | 'new' | 'milestone' | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [removing, setRemoving] = useState<Activity | null>(null)
  const [askLogo, setAskLogo] = useState(false)
  const identity = useIdentity()
  const remove = useAction((a: Activity) => deleteActivity(a.id), { invalidate: [schKeys.all], success: removing?.is_milestone ? 'Milestone removed' : 'Activity removed', onSuccess: () => setRemoving(null) })
  const set = (p: Partial<typeof f>) => setF((x) => ({ ...x, ...p }))
  const active = !!(f.q || f.status || f.who || f.from || f.to || f.milestones)

  const rows = useMemo(() => (d?.activities ?? []).filter((a) => {
    if (f.q && !`${a.code} ${a.name} ${a.assigned_to ?? ''}`.toLowerCase().includes(f.q.toLowerCase())) return false
    if (f.milestones && !a.is_milestone) return false
    if (f.who && String(a.assigned_to_id ?? '') !== (f.who === 'none' ? '' : f.who)) return false
    if (f.from && a.planned_finish < f.from) return false
    if (f.to && a.planned_start > f.to) return false
    if (f.status === 'overdue' && !a.overdue) return false
    if (f.status && f.status !== 'overdue' && statusOf(a) !== f.status) return false
    return true
  }), [d, f])
  const late = (d?.activities ?? []).filter((a) => a.overdue).sort((a, b) => (b.days_late ?? 0) - (a.days_late ?? 0))
  const milestones = (d?.activities ?? []).filter((a) => a.is_milestone).sort((a, b) => a.planned_finish.localeCompare(b.planned_finish))
  const v = s?.variance ?? 0
  const edit = (a: Activity) => manage && setEditing(a)

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Project Chart"
        description="The programme on a timeline: who is to do what by when, how far along it is, and what is running late."
        actions={<>
          {manage && <Button disabled={!job} onClick={() => setEditing('new')}><Plus /> Activity</Button>}
          {manage && <Button variant="outline" disabled={!job} onClick={() => setEditing('milestone')}><Flag /> Milestone</Button>}
          <Button variant="outline" disabled={!job} onClick={() => setDrawing(true)}>Draw from BOQ</Button>
          <Button variant="outline" disabled={!job || !d?.activities.length} onClick={() => (identity.data?.logo_url ? void printChart(identity.data.logo_url) : setAskLogo(true))}><Printer /> Print</Button>
        </>}
      />
      <div className="mb-4"><ProjectPicker value={job} onChange={(j) => { setJob(j); setF({ q: '', status: '', who: '', from: '', to: '', milestones: false }) }} id="chart-job" /></div>
      {!job ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">Choose a project to see its chart.</p> : q.isError ? (
        <div role="alert" className="flex items-center gap-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger"><AlertTriangle className="size-4" /><span className="flex-1">{q.error.message}</span><Button size="sm" variant="outline" onClick={() => q.refetch()}>Try again</Button></div>
      ) : (
        <>
          <StatGrid className="xl:grid-cols-6">
            <Stat label="Starts" value={s?.start ? formatDate(s.start) : '-'} loading={q.isPending} />
            <Stat label="Planned finish" value={s?.end ? formatDate(s.end) : '-'} sub={s?.forecast_finish && s.slip_days > 0 ? `forecast ${formatDate(s.forecast_finish)}` : undefined} tone={s && s.slip_days > 0 ? 'danger' : undefined} loading={q.isPending} />
            <Stat label="Duration" value={s?.duration_days ? `${s.duration_days} days` : '-'} sub={s?.duration_days ? `${Math.round(s.duration_days / 7)} weeks` : undefined} loading={q.isPending} />
            <Stat label="Planned / actual" value={`${s?.planned_percent ?? 0}% / ${s?.actual_percent ?? 0}%`} sub={`${v > 0 ? '+' : ''}${v} pts`} tone={v < -5 ? 'danger' : v < 0 ? 'warning' : 'success'} loading={q.isPending} />
            <Stat label="Overdue" value={s?.overdue ?? 0} tone={s?.overdue ? 'danger' : undefined} sub={s?.behind ? `+${s.behind} behind plan` : undefined} loading={q.isPending} onClick={() => { setTab('list'); set({ status: 'overdue' }) }} active={f.status === 'overdue'} />
            <Stat label="Milestones" value={`${s?.milestones_done ?? 0} of ${s?.milestones ?? 0}`} loading={q.isPending} onClick={() => setTab('milestones')} />
          </StatGrid>

          {late.length > 0 && (
            <div role="alert" className="mb-5 rounded-xl border border-danger/30 bg-danger-soft p-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-danger"><AlertTriangle className="size-4" /> {late.length} activit{late.length === 1 ? 'y is' : 'ies are'} past {late.length === 1 ? 'its' : 'their'} deadline</p>
              <ul className="mt-2 grid gap-1 text-[13px]">
                {late.slice(0, 5).map((a) => <li key={a.id}><button type="button" className="text-left hover:underline" onClick={() => edit(a)}><strong>{a.code} {a.name}</strong> - {a.days_late} day{a.days_late === 1 ? '' : 's'} late, {a.actual_percent}% done{a.assigned_to ? `, ${a.assigned_to}` : ', nobody assigned'}</button></li>)}
                {late.length > 5 && <li className="text-muted-foreground">and {late.length - 5} more - <button type="button" className="underline" onClick={() => { setTab('list'); set({ status: 'overdue' }) }}>show them all</button></li>}
              </ul>
            </div>
          )}

          <div className="mb-3 max-w-md"><Tabs label="Chart views" value={tab} onChange={setTab} items={[{ value: 'gantt', label: 'Gantt chart' }, { value: 'list', label: 'Activities', count: d?.activities.length }, { value: 'milestones', label: 'Milestones', count: milestones.length }]} /></div>

          {tab !== 'milestones' && (
            <div role="search" className="mb-3 flex flex-wrap items-center gap-2">
              <div className="relative min-w-52 flex-1 basis-56"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden /><Input aria-label="Search activities" className="pl-9" placeholder="Search activity, code or person" value={f.q} onChange={(e) => set({ q: e.target.value })} /></div>
              <div className="w-48"><Select aria-label="Status" value={f.status} placeholder="Any status" onChange={(e) => set({ status: e.target.value })} options={STATUS} /></div>
              <div className="w-48"><Select aria-label="Employee" value={f.who} placeholder="Any employee" onChange={(e) => set({ who: e.target.value })} options={[{ value: 'none', label: 'Nobody assigned' }, ...(d?.employees ?? []).map((e) => ({ value: e.id, label: e.name }))]} /></div>
              <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">From<Input type="date" aria-label="From date" className="w-36" value={f.from} max={f.to || undefined} onChange={(e) => set({ from: e.target.value })} /></label>
              <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">To<Input type="date" aria-label="To date" className="w-36" value={f.to} min={f.from || undefined} onChange={(e) => set({ to: e.target.value })} /></label>
              {active && <Button variant="ghost" size="sm" onClick={() => setF({ q: '', status: '', who: '', from: '', to: '', milestones: false })}><X /> Clear</Button>}
            </div>
          )}

          {q.isPending ? <Skeleton className="h-64 w-full" /> : !d || d.activities.length === 0 ? (
            <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No chart yet. Add the first activity, or draw one from a work order: each line becomes an activity whose progress comes from the measurement book.</p>
          ) : tab === 'gantt' ? (
            <>
              {rows.length === 0 ? <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No activity matches these filters.</p> : <Gantt rows={rows} onOpen={edit} />}
              <Curve curve={d.curve} />
            </>
          ) : tab === 'list' ? (
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table aria-label="Activities" className="w-full min-w-[56rem] border-collapse text-[13.5px]">
                  <thead className="bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2.5">Activity</th><th className="px-3">Assigned to</th><th className="px-3">Starts</th><th className="px-3">Deadline</th><th className="min-w-40 px-3">Planned / actual</th><th className="px-3">Status</th><th className="px-3 text-right">Actions</th></tr></thead>
                  <tbody>
                    {rows.length === 0 && <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">No activity matches these filters.</td></tr>}
                    {rows.map((a) => (
                      <tr key={a.id} className={`border-t border-border align-top ${a.overdue ? 'bg-danger-soft/40' : ''}`}>
                        <td className="px-3 py-2"><button type="button" className="text-left font-semibold text-primary hover:underline" onClick={() => edit(a)}>{a.is_milestone && <Flag className="mr-1 inline size-3.5" />}<span className="mr-1.5 font-mono text-xs font-normal text-muted-foreground">{a.code}</span>{a.name}</button>{a.predecessor_code && <div className="text-[11px] text-muted-foreground">after {a.predecessor_code}</div>}</td>
                        <td className="px-3 py-2">{a.assigned_to || <span className="text-muted-foreground">Nobody</span>}</td>
                        <td className="whitespace-nowrap px-3 py-2">{formatDate(a.planned_start)}</td>
                        <td className={`whitespace-nowrap px-3 py-2 ${a.overdue ? 'font-semibold text-danger' : ''}`}>{formatDate(a.planned_finish)}{a.overdue && <div className="text-[11px]">{a.days_late} day{a.days_late === 1 ? '' : 's'} late</div>}</td>
                        <td className="px-3 py-2"><ProgressBar thin percent={a.actual_percent} planned={a.planned_percent} tone={BAR[a.overdue ? 'late' : (a.state as keyof typeof BAR)] ?? 'bg-primary'} label={`${a.name} done`} /><div className="text-right text-[10px] text-muted-foreground">plan {a.planned_percent}% - done {a.actual_percent}%</div></td>
                        <td className="px-3 py-2"><Badge tone={STATUS_TONE[statusOf(a)] ?? 'neutral'} dot>{statusOf(a)}</Badge>{a.overdue && <div className="text-[11px] font-semibold text-danger">overdue</div>}{a.slip_days > 0 && !a.overdue && <div className="text-[11px] text-danger">+{a.slip_days} days</div>}{a.notes && <div className="mt-0.5 max-w-48 truncate text-[11px] text-muted-foreground" title={a.notes}>{a.notes}</div>}</td>
                        <td className="px-3 py-2"><div className="flex flex-col items-end gap-1.5">{!a.work_order_line_id && can('site.record') && a.state !== 'done' && <ProgressControl id={a.id} percent={a.actual_percent} compact />}{manage && <div className="flex gap-1.5"><Button size="sm" variant="outline" aria-label={`Edit ${a.name}`} title="Edit" onClick={() => setEditing(a)}><Pencil /></Button><Button size="sm" variant="ghost" aria-label={`Delete ${a.name}`} className="text-danger" onClick={() => setRemoving(a)}><Trash2 /></Button></div>}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : (
            <Milestones list={milestones} onEdit={edit} manage={manage} canTick={can('site.record')} onDelete={setRemoving} />
          )}
        </>
      )}
      <ActivityModal job={job} activity={editing && editing !== 'new' && editing !== 'milestone' ? editing : null} milestone={editing === 'milestone'} others={d?.activities ?? []} employees={d?.employees ?? []} teamScope={d?.team_scope} open={!!editing} onClose={() => setEditing(null)} />
      {job > 0 && d && d.activities.length > 0 && <PrintReport schedule={d} company={{ name: identity.data?.name || 'Company', address: identity.data?.address || '', gstin: identity.data?.gstin || '', logo_url: identity.data?.logo_url || '' }} />}
      <LogoPrintModal open={askLogo} onClose={() => setAskLogo(false)} onPrint={(logo) => { setAskLogo(false); void printChart(logo) }} />
      {drawing && <BoqPickerModal job={job} onClose={() => setDrawing(false)} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.name ?? (removing?.is_milestone ? 'this milestone' : 'this activity')}?`} description="Do you want to delete this? It cannot be undone." tone="danger" confirmLabel="Yes" cancelLabel="Cancel" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}

/** The stages that mark the project: when each is due, whether it has been reached, and what is holding it up. */
function Milestones({ list, onEdit, manage, canTick, onDelete }: { list: Activity[]; onEdit: (a: Activity) => void; manage: boolean; canTick: boolean; onDelete: (a: Activity) => void }) {
  const tick = useAction((a: Activity) => setProgress(a.id, 100), { invalidate: [schKeys.all], success: 'Milestone reached' })
  if (list.length === 0) return <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No milestones yet. {manage ? 'Add one with the Milestone button: a handover, a pour, an approval.' : ''}</p>
  const t = today()
  return (
    <ol aria-label="Milestones" className="grid gap-2">
      {list.map((a) => {
        const done = a.state === 'done'
        const days = Math.round((new Date(a.planned_finish).getTime() - new Date(t).getTime()) / 86400000)
        return (
          <li key={a.id} className={`flex flex-wrap items-center gap-3 rounded-xl border p-3.5 ${a.overdue ? 'border-danger/40 bg-danger-soft/40' : 'border-border bg-card'}`}>
            <Flag className={`size-5 shrink-0 ${done ? 'text-success' : a.overdue ? 'text-danger' : 'text-primary'}`} aria-hidden />
            <div className="min-w-0 flex-1">
              <button type="button" className="text-left font-semibold hover:underline" onClick={() => onEdit(a)}>{a.name}</button>
              <p className="text-xs text-muted-foreground">Due {formatDate(a.planned_finish)}{a.assigned_to && ` - ${a.assigned_to}`}{a.predecessor_code && ` - after ${a.predecessor_code}`}</p>{a.notes && <p className="mt-0.5 text-xs text-muted-foreground">{a.notes}</p>}
            </div>
            <Badge tone={done ? 'success' : a.overdue ? 'danger' : 'info'} dot>{done ? `Reached${a.actual_percent ? '' : ''}` : a.overdue ? `${a.days_late} days late` : days === 0 ? 'Due today' : `In ${days} days`}</Badge>
            {!done && canTick && !a.work_order_line_id && <Button size="sm" variant="outline" loading={tick.isPending && tick.variables?.id === a.id} onClick={() => tick.mutate(a)}>Mark reached</Button>}
            {manage && <Button size="sm" variant="ghost" className="text-danger" aria-label={`Delete ${a.name}`} onClick={() => onDelete(a)}><Trash2 /></Button>}
          </li>
        )
      })}
    </ol>
  )
}
