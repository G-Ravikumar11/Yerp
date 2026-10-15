import { takePhoto } from '@/lib/mobile'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Camera, HardHat, X } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select, Skeleton, Textarea } from '@/components/ui'
import { PromptModal } from '@/components/data/PromptModal'
import { TRADES, WEATHER, diaryKeys, reopenDiary, signOffDiary, useDiaries, useDiary, type DiaryDetail, type DiaryInput, type LabourLine, type PlantLine, type WorkUpdate } from '@/api/diary'
import { schKeys, type DayRow, type DayTask } from '@/api/schedule'
import { fileKeys, noFilter, uploadFiles, useFiles } from '@/api/files'
import { useWorkers } from '@/api/safety'
import { Tile } from '@/components/data/FilesModal'
import { sendOrQueue } from '@/stores/offline'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { PlannedWork, type TaskState } from './PlannedWork'

const blankLabour = (): LabourLine => ({ trade: TRADES[0], agency: 'Own', headcount: 0, hours: 0, rate: 0 })
const blankPlant = (): PlantLine => ({ plant: '', worked_hours: 0, idle_hours: 0, rate: 0 })

export function DiaryFormModal({ job, id, onClose, onOpen }: { job: number; id: number | 'new' | null; onClose: () => void; onOpen: (id: number) => void }) {
  const q = useDiary(typeof id === 'number' ? id : null)
  return (
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={id === 'new' ? 'Record a day' : q.data ? `Day of ${q.data.diary_date}` : 'Site diary'} description="Who turned up, what the weather did, what got built and what stopped it." size="xl">
      {id === 'new' ? <Form key="new" job={job} day={null} onClose={onClose} onOpen={onOpen} /> : id && (q.data ? <Form key={id} job={job} day={q.data} onClose={onClose} onOpen={onOpen} /> : <Skeleton className="h-64 w-full" />)}
    </Modal>
  )
}

function Form({ job, day, onClose, onOpen }: { job: number; day: DiaryDetail | null; onClose: () => void; onOpen: (id: number) => void }) {
  const { can } = useSession()
  const locked = !!day && day.status !== 'DRAFT'
  const [date, setDate] = useState(day?.diary_date ?? today())
  const [weather, setWeather] = useState(day?.weather ?? 'Clear')
  // A signed-off day is opened for changes on purpose, with a reason that stays on the diary, and signed again after.
  const [reopening, setReopening] = useState(false)
  const reopen = useAction((reason: string) => reopenDiary(day!.id, reason), { invalidate: [diaryKeys.all], success: (r) => r.message, onSuccess: () => setReopening(false) })
  // A site has one diary a day. Say so as soon as the date names a day that has one, rather than when saving.
  const days = useDiaries(job)
  const clash = !day ? days.data?.diaries.find((d) => d.diary_date === date) : undefined
  const [rain, setRain] = useState(day?.rain_hours ?? 0)
  const [hours, setHours] = useState(day?.working_hours || 8)
  const [work, setWork] = useState(day?.work_done ?? '')
  const [holdups, setHoldups] = useState(day?.holdups ?? '')
  const [instructions, setInstructions] = useState(day?.instructions ?? '')
  const [visitors, setVisitors] = useState(day?.visitors ?? '')
  const [safety, setSafety] = useState(day?.safety_note ?? '')
  // Always one blank row past the end, so adding a trade is typing rather than hunting for a button.
  const [labour, setLabour] = useState<LabourLine[]>([...(day?.labour ?? []), blankLabour(), blankLabour()])
  const [plant, setPlant] = useState<PlantLine[]>([...(day?.plant ?? []), blankPlant()])
  const [picking, setPicking] = useState(false)
  const [photos, setPhotos] = useState<File[]>([])
  // What the day reports about the planned work, kept as differences from what the plan says now.
  const [taskState, setTaskState] = useState<Record<number, TaskState>>({})
  const [percent, setPercent] = useState<Record<number, number>>({})
  const [planned, setPlanned] = useState<{ tasks: Record<number, DayTask>; rows: Record<number, DayRow> }>({ tasks: {}, rows: {} })
  useEffect(() => { setTaskState({}); setPercent({}); setPlanned({ tasks: {}, rows: {} }) }, [date])
  const tickTask = (t: DayTask, state: TaskState) => {
    setTaskState((m) => ({ ...m, [t.id]: state }))
    setPlanned((p) => ({ ...p, tasks: { ...p.tasks, [t.id]: t } }))
  }
  const setProgressOf = (r: DayRow, pct: number) => {
    setPercent((m) => ({ ...m, [r.id]: pct }))
    setPlanned((p) => ({ ...p, rows: { ...p.rows, [r.id]: r } }))
  }
  const camera = useRef<HTMLInputElement>(null)
  const saved = useFiles('diary', day?.id ?? 0, noFilter)
  const edit = <T,>(list: T[], set: (l: T[]) => void, i: number, patch: Partial<T>) => set(list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const totals = useMemo(() => {
    const d = hours || 8
    let md = 0, lc = 0, pc = 0
    for (const l of labour) { const share = (l.hours || d) / d; md += l.headcount * share; lc += l.headcount * share * l.rate }
    for (const p of plant) pc += (p.worked_hours + p.idle_hours) * p.rate
    return { md: Math.round(md * 100) / 100, lc, pc }
  }, [labour, plant, hours])
  const body = (): DiaryInput => ({
    job_id: job, diary_date: date, weather, rain_hours: rain, working_hours: hours, work_done: work, holdups, instructions, visitors, safety_note: safety,
    labour: labour.filter((l) => l.headcount > 0).map((l) => ({ ...l, hours: l.hours || hours })),
    plant: plant.filter((p) => p.plant.trim()),
    work_updates: [
      // Only what the buttons say: the words written under "Work done" never move the plan.
      ...Object.entries(taskState)
        .filter(([id, s]) => planned.tasks[Number(id)] && (planned.tasks[Number(id)].done !== s.done || (!s.done && Math.round(planned.tasks[Number(id)].percent) !== Math.round(s.percent))))
        .map(([id, s]): WorkUpdate => (s.done ? { task_id: Number(id), done: true } : s.percent > 0 ? { task_id: Number(id), percent: s.percent } : { task_id: Number(id), done: false })),
      ...Object.entries(percent).filter(([id, pct]) => planned.rows[Number(id)] && Math.round(planned.rows[Number(id)].actual_percent) !== Math.round(pct)).map(([id, pct]): WorkUpdate => ({ activity_id: Number(id), percent: pct })),
    ],
  })
  const save = useAction(
    async (signOff: boolean) => {
      const sent = await sendOrQueue<{ diary: { id: number }; message?: string }>({ method: day ? 'PUT' : 'POST', url: day ? `/api/diary/${day.id}` : '/api/diary', body: body(), label: `Site diary ${date}` })
      if (sent.queued) return { message: 'No signal. The day is kept on this device and goes up by itself when you are back online.' + (signOff ? ' Sign it off once it has gone up.' : '') }
      const id = sent.result.diary.id
      if (photos.length) {
        const { failed } = await uploadFiles(photos, 'diary', id)
        if (failed.length) toast.error(failed.join(' - '))
      }
      if (signOff) return { message: (await signOffDiary(id)).message }
      return { message: sent.result.message ?? 'Saved.' }
    },
    { invalidate: [diaryKeys.all, fileKeys.all, schKeys.all], success: (r) => r.message, onSuccess: onClose },
  )
  const pickPhotos = (list: ArrayLike<File> | null) => {
    const chosen = list ? Array.from(list) : [] // copied now: the input is emptied straight after, and a FileList empties with it
    if (chosen.length) setPhotos((p) => [...p, ...chosen])
  }
  const num = 'text-right'
  return (
    <div>
      {locked && (
        <p className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-2.5 text-[13px]">
          <span className="flex-1">Signed off on {day?.submitted_at}. A diary that can be rewritten quietly afterwards is worth nothing in a claim, so changing it needs a reason, which stays on the diary.</span>
          {can('site.signoff') && <Button size="sm" variant="outline" onClick={() => setReopening(true)}>Edit</Button>}
        </p>
      )}
      {!!day?.amendments?.length && (
        <div aria-label="Amended after sign-off" className="mb-3 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">
          <div className="mb-0.5 font-semibold">Changed after it was signed off</div>
          <ul className="grid gap-0.5">{day.amendments.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </div>
      )}
      <PromptModal open={reopening} title="Edit a signed-off day" description="The day opens for changes and has to be signed off again. Your reason is kept on the diary with your name and the time." fields={[{ key: 'reason', label: 'Why is it being changed?', required: true }]} confirm="Open for editing" busy={reopen.isPending} error={reopen.error?.message} onSubmit={(v) => reopen.mutate(v.reason.trim())} onClose={() => setReopening(false)} />
      {clash && (
        <p role="alert" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">
          <span className="flex-1">
            {clash.status === 'DRAFT'
              ? `There is already a diary for ${date} on this site. A site has one diary a day, so add to that one.`
              : `The diary for ${date} has been signed off, so it can no longer be changed. Choose another day.`}
          </span>
          <Button size="sm" variant="outline" onClick={() => onOpen(clash.id)}>{clash.status === 'DRAFT' ? 'Open that day' : 'View it'}</Button>
        </p>
      )}
      <fieldset disabled={locked} className="min-w-0 border-0 p-0">
        <div className="grid gap-4 sm:grid-cols-4">
          <Field label="Date" htmlFor="dy-date"><Input id="dy-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Weather" htmlFor="dy-weather"><Select id="dy-weather" value={weather} onChange={(e) => setWeather(e.target.value)} options={WEATHER.map((w) => ({ value: w, label: w }))} /></Field>
          <Field label="Rain (hours)" htmlFor="dy-rain"><NumField id="dy-rain" value={rain} onValue={setRain} /></Field>
          <Field label="Working hours" htmlFor="dy-hours"><NumField id="dy-hours" value={hours} onValue={setHours} /></Field>
          <Field label="Work done" htmlFor="dy-work" className="sm:col-span-2"><Textarea id="dy-work" rows={3} value={work} onChange={(e) => setWork(e.target.value)} /></Field>
          <Field label="What held it up" htmlFor="dy-hold" className="sm:col-span-2"><Textarea id="dy-hold" rows={3} value={holdups} onChange={(e) => setHoldups(e.target.value)} /></Field>
          <Field label="Instructions received" htmlFor="dy-ins" className="sm:col-span-2"><Textarea id="dy-ins" rows={2} value={instructions} onChange={(e) => setInstructions(e.target.value)} /></Field>
          <Field label="Visitors" htmlFor="dy-vis"><Textarea id="dy-vis" rows={2} value={visitors} onChange={(e) => setVisitors(e.target.value)} /></Field>
          <Field label="Safety note" htmlFor="dy-safe"><Textarea id="dy-safe" rows={2} value={safety} onChange={(e) => setSafety(e.target.value)} /></Field>
        </div>
        <PlannedWork job={job} date={date} taskState={taskState} onTask={tickTask} percent={percent} onPercent={setProgressOf} disabled={locked} />
        <h3 className="mb-2 mt-5 text-sm font-semibold">Labour on site</h3>
        <div className="grid gap-2">
          {labour.map((l, i) => {
            const named = !!l.worker_ids?.length
            return (
              <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[1.2fr_1.2fr_.7fr_.7fr_.8fr]">
                {named ? (
                  <div className="flex items-center gap-1.5 truncate rounded-md border border-input bg-muted/40 px-3 text-sm" title={`${l.trade} - ${l.workers?.[0]?.name}`}>
                    <HardHat className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{l.workers?.[0]?.name} <span className="text-muted-foreground">({l.trade})</span></span>
                  </div>
                ) : (
                  <Select aria-label={`Trade ${i + 1}`} value={l.trade} onChange={(e) => edit(labour, setLabour, i, { trade: e.target.value })} options={TRADES.map((t) => ({ value: t, label: t }))} />
                )}
                <Input aria-label={`Agency ${i + 1}`} value={l.agency} placeholder="Own or the contractor" onChange={(e) => edit(labour, setLabour, i, { agency: e.target.value })} />
                <NumField aria-label={`Headcount ${i + 1}`} placeholder="Heads" className={num} value={l.headcount} disabled={named} onValue={(n) => edit(labour, setLabour, i, { headcount: n })} />
                <NumField aria-label={`Hours ${i + 1}`} placeholder="Hours" className={num} value={l.hours} onValue={(n) => edit(labour, setLabour, i, { hours: n })} />
                <NumField aria-label={`Rate ${i + 1}`} placeholder="Rate" className={num} value={l.rate} onValue={(n) => edit(labour, setLabour, i, { rate: n })} />
              </div>
            )
          })}
        </div>
        {!locked && (
          <div className="mt-1 flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={() => setLabour([...labour, blankLabour()])}>Add a trade</Button>
            <Button size="sm" variant="ghost" onClick={() => setPicking(true)}><HardHat /> Add from Workers &amp; Safety</Button>
          </div>
        )}
        <WorkerPicker job={job} open={picking} onClose={() => setPicking(false)}
          already={new Set(labour.flatMap((l) => l.worker_ids ?? []))}
          onAdd={(picked) => { setLabour([...labour, ...picked.map((w): LabourLine => ({ trade: w.trade, agency: 'Own', headcount: 1, hours, rate: 0, worker_ids: [w.id], workers: [{ id: w.id, name: w.name, trade: w.trade }] }))]); setPicking(false) }} />
        <h3 className="mb-2 mt-5 text-sm font-semibold">Plant and equipment</h3>
        <div className="grid gap-2">
          {plant.map((p, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[2fr_1fr_1fr_1fr]">
              <Input aria-label={`Plant ${i + 1}`} value={p.plant} placeholder="JCB 3DX" onChange={(e) => edit(plant, setPlant, i, { plant: e.target.value })} />
              <NumField aria-label={`Worked ${i + 1}`} placeholder="Worked h" className={num} value={p.worked_hours} onValue={(n) => edit(plant, setPlant, i, { worked_hours: n })} />
              <NumField aria-label={`Idle ${i + 1}`} placeholder="Idle h" className={num} value={p.idle_hours} onValue={(n) => edit(plant, setPlant, i, { idle_hours: n })} />
              <NumField aria-label={`Plant rate ${i + 1}`} placeholder="Rate / h" className={num} value={p.rate} onValue={(n) => edit(plant, setPlant, i, { rate: n })} />
            </div>
          ))}
        </div>
        {!locked && <Button size="sm" variant="ghost" className="mt-1" onClick={() => setPlant([...plant, blankPlant()])}>Add a machine</Button>}
      </fieldset>
      <p aria-label="Totals" className="mt-4 rounded-lg bg-muted/50 p-3 text-sm"><strong>{totals.md}</strong> mandays - labour <strong>{formatINR(totals.lc)}</strong> - plant <strong>{formatINR(totals.pc)}</strong> - the day cost <strong>{formatINR(totals.lc + totals.pc)}</strong></p>
      {!locked && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input ref={camera} type="file" accept="image/*" capture="environment" multiple className="sr-only" aria-label="Photos of the day" onChange={(e) => { pickPhotos(e.target.files); e.target.value = '' }} />
          <Button variant="outline" size="sm" onClick={() => void takePhoto(camera.current, pickPhotos)}><Camera /> Photos of the day</Button>
          {photos.map((f, i) => <PickedPhoto key={i} f={f} onRemove={() => setPhotos(photos.filter((_, j) => j !== i))} />)}
        </div>
      )}
      {saved.data?.files.length ? (
        <div className="mt-4"><p className="mb-2 text-sm font-medium">Photos kept on this day</p><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{saved.data.files.map((f) => <Tile key={f.id} f={f} />)}</div></div>
      ) : null}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>{locked ? 'Close' : 'Cancel'}</Button>
        {!locked && <Button variant="outline" loading={save.isPending} disabled={!!clash} onClick={() => save.mutate(false)}>Save the day</Button>}
        {!locked && can('site.signoff') && <Button loading={save.isPending} disabled={!!clash} onClick={() => save.mutate(true)}>Save and sign off</Button>}
      </div>
    </div>
  )
}

/** Workers screened for this site, so today's diary can name them instead of only counting heads. One already on
 * today's list (by another row) cannot be picked twice. */
function WorkerPicker({ job, open, already, onAdd, onClose }: { job: number; open: boolean; already: Set<number>; onAdd: (picked: { id: number; name: string; trade: string }[]) => void; onClose: () => void }) {
  const q = useWorkers(job)
  const [checked, setChecked] = useState<Record<number, boolean>>({})
  const available = (q.data?.workers ?? []).filter((w) => !already.has(w.id))
  const toggle = (id: number) => setChecked((c) => ({ ...c, [id]: !c[id] }))
  const add = () => {
    const picked = available.filter((w) => checked[w.id]).map((w) => ({ id: w.id, name: w.name, trade: w.trade }))
    setChecked({})
    onAdd(picked)
  }
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Add from Workers & Safety" description="Pick who is on site today - their trade comes with them, so nobody has to be typed in by hand.">
      {q.isPending ? <Skeleton className="h-32 w-full" /> : available.length === 0 ? (
        <p className="text-sm text-muted-foreground">{q.data?.workers.length ? 'Everyone screened for this site is already on today\'s list.' : 'Nobody has been screened for this site yet, in Workers & Safety.'}</p>
      ) : (
        <div className="grid max-h-80 gap-1 overflow-y-auto">
          {available.map((w) => (
            <label key={w.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/50">
              <input type="checkbox" checked={!!checked[w.id]} onChange={() => toggle(w.id)} />
              <span className="flex-1">{w.name}</span>
              <span className="text-xs text-muted-foreground">{w.trade}</span>
            </label>
          ))}
        </div>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button disabled={!Object.values(checked).some(Boolean)} onClick={add}>Add to today</Button>
      </div>
    </Modal>
  )
}

/** A photo just taken, shown at once from the phone itself, before it has gone up. */
function PickedPhoto({ f, onRemove }: { f: File; onRemove: () => void }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    const u = URL.createObjectURL(f)
    setSrc(u)
    return () => URL.revokeObjectURL(u)
  }, [f])
  return (
    <span className="relative inline-block">
      {src && <img src={src} alt={f.name} className="size-20 rounded-md border border-border object-cover" />}
      <button type="button" aria-label={`Remove ${f.name}`} onClick={onRemove} className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-foreground text-background"><X className="size-3" /></button>
    </span>
  )
}
