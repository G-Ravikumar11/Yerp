import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Input } from '@/components/ui'
import { addTask, deleteTask, editTask, schKeys, type DayRow, type DayTask } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'

/** What is to be done on this day, in words: add a task (under an activity if it belongs to one), tick it off, remove it. */
export function DayTasks({ job, on, tasks, activities, can }: { job: number; on: string; tasks: DayTask[]; activities: Pick<DayRow, 'id' | 'code' | 'name'>[]; can: boolean }) {
  const [text, setText] = useState('')
  const [activity, setActivity] = useState('')
  const add = useAction(() => addTask(job, { text: text.trim(), date: on, activity_id: activity ? Number(activity) : null }), {
    invalidate: [schKeys.all],
    success: 'Task added',
    onSuccess: () => setText(''),
  })
  const tick = useAction((v: { t: DayTask; done: boolean }) => editTask(v.t.id, { done: v.done }), { invalidate: [schKeys.all] })
  const remove = useAction((t: DayTask) => deleteTask(t.id), { invalidate: [schKeys.all], success: 'Task removed' })
  const done = tasks.filter((t) => t.done).length
  return (
    <section aria-label="Tasks for the day" className="mb-6">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">Tasks for the day</h2>
        <span className="text-xs text-muted-foreground">what is to be done, in words</span>
        <Badge tone={tasks.length && done === tasks.length ? 'success' : 'neutral'}>{done}/{tasks.length} done</Badge>
      </div>
      {tasks.length === 0 ? (
        <p className="mb-2 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">Nothing written down for this day yet.</p>
      ) : (
        <ul className="mb-2 grid gap-1.5">
          {tasks.map((t) => (
            <li key={t.id} className="flex items-start gap-3 rounded-xl border border-border bg-card px-3 py-2 shadow-card">
              <input type="checkbox" checked={t.done} disabled={!can} aria-label={`Done: ${t.text}`} className="mt-1 size-4 accent-[var(--primary)]" onChange={(e) => tick.mutate({ t, done: e.target.checked })} />
              <div className="min-w-0 flex-1">
                <div className={cn('text-sm', t.done && 'text-muted-foreground line-through')}>{t.text}</div>
                <div className="text-[11px] text-muted-foreground">
                  {t.activity && <span className="mr-2">{t.activity}</span>}
                  {t.done ? `Done ${t.done_at}${t.done_by_name ? ` by ${t.done_by_name}` : ''}` : t.created_by_name ? `Added by ${t.created_by_name}` : ''}
                </div>
              </div>
              {can && <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" aria-label={`Remove ${t.text}`} onClick={() => remove.mutate(t)}><Trash2 /></Button>}
            </li>
          ))}
        </ul>
      )}
      {can && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate() }}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Pour the slab, 8 labourers" maxLength={300} aria-label="New task" className="min-w-64 flex-1" />
          <select value={activity} onChange={(e) => setActivity(e.target.value)} aria-label="Under which activity" className="h-10 rounded-md border border-input bg-card px-2 text-sm text-foreground">
            <option value="">Not under an activity</option>
            {activities.map((a) => <option key={a.id} value={a.id}>{`${a.code} ${a.name}`.trim()}</option>)}
          </select>
          <Button type="submit" disabled={!text.trim()} loading={add.isPending}><Plus /> Add task</Button>
        </form>
      )}
    </section>
  )
}
