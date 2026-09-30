import { useMemo, useRef, useState } from 'react'
import { Camera, X } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select, Skeleton, Textarea } from '@/components/ui'
import { TRADES, WEATHER, diaryKeys, signOffDiary, useDiary, type DiaryDetail, type DiaryInput, type LabourLine, type PlantLine } from '@/api/diary'
import { fileKeys, uploadFiles } from '@/api/files'
import { sendOrQueue } from '@/stores/offline'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const blankLabour = (): LabourLine => ({ trade: TRADES[0], agency: 'Own', headcount: 0, hours: 0, rate: 0 })
const blankPlant = (): PlantLine => ({ plant: '', worked_hours: 0, idle_hours: 0, rate: 0 })

export function DiaryFormModal({ job, id, onClose }: { job: number; id: number | 'new' | null; onClose: () => void }) {
  const q = useDiary(typeof id === 'number' ? id : null)
  return (
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={id === 'new' ? 'Record a day' : q.data ? `Day of ${q.data.diary_date}` : 'Site diary'} description="Who turned up, what the weather did, what got built and what stopped it." size="xl">
      {id === 'new' ? <Form key="new" job={job} day={null} onClose={onClose} /> : id && (q.data ? <Form key={id} job={job} day={q.data} onClose={onClose} /> : <Skeleton className="h-64 w-full" />)}
    </Modal>
  )
}

function Form({ job, day, onClose }: { job: number; day: DiaryDetail | null; onClose: () => void }) {
  const { can } = useSession()
  const locked = !!day && day.status !== 'DRAFT'
  const [date, setDate] = useState(day?.diary_date ?? today())
  const [weather, setWeather] = useState(day?.weather ?? 'Clear')
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
  const [photos, setPhotos] = useState<File[]>([])
  const camera = useRef<HTMLInputElement>(null)
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
    { invalidate: [diaryKeys.all, fileKeys.all], success: (r) => r.message, onSuccess: onClose },
  )
  const pickPhotos = (list: FileList | null) => {
    const chosen = list ? [...list] : [] // copied now: the input is emptied straight after, and a FileList empties with it
    if (chosen.length) setPhotos((p) => [...p, ...chosen])
  }
  const num = 'text-right'
  return (
    <div>
      {locked && <p className="mb-3 rounded-lg bg-muted/50 p-2.5 text-[13px]">Signed off on {day?.submitted_at}. A diary that can be rewritten afterwards is worth nothing in a claim.</p>}
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
        <h3 className="mb-2 mt-5 text-sm font-semibold">Labour on site</h3>
        <div className="grid gap-2">
          {labour.map((l, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[1.2fr_1.2fr_.7fr_.7fr_.8fr]">
              <Select aria-label={`Trade ${i + 1}`} value={l.trade} onChange={(e) => edit(labour, setLabour, i, { trade: e.target.value })} options={TRADES.map((t) => ({ value: t, label: t }))} />
              <Input aria-label={`Agency ${i + 1}`} value={l.agency} placeholder="Own or the gang" onChange={(e) => edit(labour, setLabour, i, { agency: e.target.value })} />
              <NumField aria-label={`Headcount ${i + 1}`} placeholder="Heads" className={num} value={l.headcount} onValue={(n) => edit(labour, setLabour, i, { headcount: n })} />
              <NumField aria-label={`Hours ${i + 1}`} placeholder="Hours" className={num} value={l.hours} onValue={(n) => edit(labour, setLabour, i, { hours: n })} />
              <NumField aria-label={`Rate ${i + 1}`} placeholder="Rate" className={num} value={l.rate} onValue={(n) => edit(labour, setLabour, i, { rate: n })} />
            </div>
          ))}
        </div>
        {!locked && <Button size="sm" variant="ghost" className="mt-1" onClick={() => setLabour([...labour, blankLabour()])}>Add a trade</Button>}
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
          <Button variant="outline" size="sm" onClick={() => camera.current?.click()}><Camera /> Photos of the day</Button>
          {photos.map((f, i) => <span key={i} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs">{f.name.slice(0, 18)}<button type="button" aria-label={`Remove ${f.name}`} onClick={() => setPhotos(photos.filter((_, j) => j !== i))}><X className="size-3" /></button></span>)}
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>{locked ? 'Close' : 'Cancel'}</Button>
        {!locked && <Button variant="outline" loading={save.isPending} onClick={() => save.mutate(false)}>Save the day</Button>}
        {!locked && can('site.signoff') && <Button loading={save.isPending} onClick={() => save.mutate(true)}>Save and sign off</Button>}
      </div>
    </div>
  )
}
