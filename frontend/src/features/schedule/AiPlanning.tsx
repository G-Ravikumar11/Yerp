import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { applyDraft, askPlan, draftProgramme, reviewPlan, suggestDay, type DayIdeas, type DraftSource, type PlanAnswer, type PlanDraft, type PlanReview } from '@/api/aiPlanning'
import { useBoqs } from '@/api/boq'
import { addTask, schKeys, useWorkOrdersOf } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const
const QUESTIONS = ['What is holding the project back?', 'Which activities start in the next two weeks?', 'When will we finish at this pace?']

/** Delay flags worked out by plain rules and put in words, and a question box that answers from the programme's own figures. Nothing is changed. */
export function AiPlanPanel({ job }: { job: number }) {
  const [review, setReview] = useState<PlanReview | null>(null)
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState<PlanAnswer | null>(null)
  const run = useAction(() => reviewPlan(job), { success: false, onSuccess: setReview })
  const go = useAction((question: string) => askPlan(job, question), { success: false, onSuccess: setAnswer })
  const ask = (question: string) => { if (question.trim()) { setQ(question); go.mutate(question) } }
  return (
    <div className="mb-5 rounded-lg border border-border px-4 py-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Check for delays</Button>
        {!review && <span className="text-muted-foreground">Looks for late and slipping activities and work waiting on something behind.</span>}
      </div>
      {review && (
        <div aria-label="Delay check" className="mt-3 grid gap-2">
          {review.summary && <p>{review.summary}</p>}
          {!review.available && review.message && <p className="text-muted-foreground">{review.message}</p>}
          {review.findings.length === 0 ? <p className="text-muted-foreground">Nothing is running late.</p> : (
            <ul className="grid gap-1">{review.findings.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level}</Badge><span>{f.text}</span></li>)}</ul>
          )}
        </div>
      )}
      <div className="mt-3 border-t border-border pt-3">
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); ask(q) }}>
          <Input aria-label="Ask about this plan" className="h-9 min-w-56 flex-1" placeholder="Ask about this plan, e.g. what is holding it back?" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button size="sm" type="submit" variant="outline" loading={go.isPending} disabled={!q.trim()}>Ask</Button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5">{QUESTIONS.map((s) => <button key={s} type="button" className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground" onClick={() => ask(s)}>{s}</button>)}</div>
        {answer && <p aria-label="Answer" className="mt-2 text-sm">{answer.available ? answer.answer : <span className="text-muted-foreground">{answer.message}</span>}</p>}
      </div>
    </div>
  )
}

/** Tasks suggested for the day from what is running, overdue and starting. Each is added only when someone accepts it. */
export function AiDayTasks({ job, on, canAdd }: { job: number; on: string; canAdd: boolean }) {
  const [ideas, setIdeas] = useState<DayIdeas | null>(null)
  const run = useAction(() => suggestDay(job, on), { success: false, onSuccess: setIdeas })
  const add = useAction((i: number) => addTask(job, { text: ideas!.tasks[i].text, date: on, activity_id: ideas!.tasks[i].activity_id }), {
    invalidate: [schKeys.all], success: 'Task added',
    onSuccess: (_r, i) => setIdeas((cur) => cur && { ...cur, tasks: cur.tasks.filter((_t, k) => k !== i) }),
  })
  return (
    <div className="mb-4 rounded-lg border border-border px-4 py-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Suggest tasks for {on === today() ? 'today' : formatDate(on)}</Button>
        {!ideas && <span className="text-muted-foreground">Turns what is running, overdue and starting into a short list. You choose which to add.</span>}
      </div>
      {ideas && (
        <div aria-label="Suggested tasks" className="mt-3 grid gap-1.5">
          {!ideas.available && ideas.message && <p className="text-muted-foreground">{ideas.message}</p>}
          {ideas.available && ideas.tasks.length === 0 && <p className="text-muted-foreground">{ideas.message || 'No more tasks to suggest.'}</p>}
          {ideas.tasks.map((t, i) => (
            <div key={`${t.text}-${i}`} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1">{t.text}{t.activity && <span className="text-muted-foreground"> · {t.activity}</span>}</span>
              {canAdd && <Button size="sm" variant="ghost" loading={add.isPending && add.variables === i} onClick={() => add.mutate(i)}>Add</Button>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const plus = (days: number) => { const d = new Date(); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

/** Ask for a programme from the project's BOQ - for this business, the client's order - or from a placed work order.
 * The proposal is shown for checking and saved only on the button. */
export function AiDraftModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const orders = useWorkOrdersOf(job)
  const boqs = useBoqs()
  const [from, setFrom] = useState('')
  const [start, setStart] = useState(today())
  const [finish, setFinish] = useState(() => plus(90))
  const [draft, setDraft] = useState<PlanDraft | null>(null)
  const boq = (boqs.data?.boqs ?? []).find((b) => b.job_id === job)
  const sources = [
    ...(boq ? [{ value: 'boq', label: `${boq.number} - the BOQ` }] : []),
    ...(orders.data ?? []).map((w) => ({ value: String(w.id), label: `${w.number} - work order` })),
  ]
  const pick = from || sources[0]?.value || ''
  const source: DraftSource = pick === 'boq' ? { boq: true } : { work_order_id: Number(pick) }
  // A list that could not be read (no right to the BOQs, say) is simply not a source; only a list still coming is waited for.
  const loading = (boqs.isPending && boqs.fetchStatus !== 'idle') || (orders.isPending && orders.fetchStatus !== 'idle')
  const make = useAction(() => draftProgramme(job, source, start, finish), { success: false, onSuccess: setDraft })
  const save = useAction(() => applyDraft(job, source, draft?.activities ?? []), { invalidate: [schKeys.all], onSuccess: () => { setDraft(null); onClose() } })
  const rows = draft?.available ? draft.activities : []
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Draft a programme with AI" description="Suggests an order of work and dates for each line of the BOQ or a work order. Check it before adding it.">
      {sources.length === 0 && !loading ? (
        <p className="text-sm">This project has no BOQ yet to draft from. Make its BOQ first, then draft the programme from it. <Link className="font-medium text-primary hover:underline" to="/projects/boq" onClick={onClose}>Open BOQ</Link></p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Draft from" htmlFor="ad-wo" className="sm:col-span-2"><Select id="ad-wo" value={pick} onChange={(e) => { setFrom(e.target.value); setDraft(null) }} options={sources} /></Field>
          <Field label="The work starts on" htmlFor="ad-start"><Input id="ad-start" type="date" value={start} onChange={(e) => { setStart(e.target.value); setDraft(null) }} /></Field>
          <Field label="And finishes by" htmlFor="ad-finish"><Input id="ad-finish" type="date" value={finish} onChange={(e) => { setFinish(e.target.value); setDraft(null) }} /></Field>
          <div className="sm:col-span-2"><Button variant="outline" loading={make.isPending} disabled={!pick || !start || !finish} onClick={() => make.mutate()}><Sparkles /> Suggest a programme</Button></div>
        </div>
      )}
      {draft && !draft.available && <p role="alert" className="mt-4 text-sm text-muted-foreground">{draft.message}</p>}
      {rows.length > 0 && (
        <table aria-label="Proposed programme" className="mt-4 w-full text-left text-[13px]">
          <thead className="text-xs text-muted-foreground"><tr><th className="py-1 pr-2 font-medium">Activity</th><th className="px-2 font-medium">Starts</th><th className="px-2 font-medium">Finishes</th><th className="pl-2 font-medium">After</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.line_id} className="border-t border-border">
              <td className="py-1.5 pr-2">{r.name}</td><td className="px-2">{formatDate(r.start)}</td><td className="px-2">{formatDate(r.finish)}</td>
              <td className="pl-2 text-muted-foreground">{rows.find((x) => x.line_id === r.after_line_id)?.name ?? '-'}</td>
            </tr>))}</tbody>
        </table>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {(make.error || save.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(make.error ?? save.error)?.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={rows.length === 0} onClick={() => save.mutate()}>Add to the programme</Button>
      </div>
    </Modal>
  )
}
