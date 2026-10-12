import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input } from '@/components/ui'
import { addTask, deleteTask, editTask, schKeys, type DayRow } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { ProgressBar } from './ProgressBar'
import { ProgressControl } from './ProgressControl'

/**
 * One activity opened up: the tasks under it. Pressing Done on a task raises the activity's bar by that task's share
 * of it - the work is done a task at a time, and the bar is how many of them are.
 */
export function ActivityPanel({ job, row, on, can, tone }: { job: number; row: DayRow; on: string; can: boolean; tone: string }) {
  const [text, setText] = useState('')
  const [day, setDay] = useState(on)
  const add = useAction(() => addTask(job, { text: text.trim(), date: day, activity_id: row.id }), { invalidate: [schKeys.all], success: 'Task added', onSuccess: () => setText('') })
  const tick = useAction((v: { id: number; done: boolean }) => editTask(v.id, { done: v.done }), { invalidate: [schKeys.all] })
  const remove = useAction((id: number) => deleteTask(id), { invalidate: [schKeys.all], success: 'Task removed' })
  return (
    <div className="rounded-lg border border-primary/40 bg-card p-3 shadow-card" aria-label={`Tasks of ${row.name}`}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="mr-2 font-mono text-xs text-muted-foreground">{row.code}</span>
          <span className="font-semibold">{row.name}</span>
          <span className="ml-2 text-[11px] text-muted-foreground">{row.planned_start} to {row.planned_finish}</span>
        </div>
        <span className="text-xs text-muted-foreground">{row.tasks_done} of {row.tasks_total} tasks done</span>
      </div>
      <ProgressBar percent={row.actual_percent} planned={row.planned_percent} tone={tone} label={`${row.name} done`} className="mb-3" />

      {row.tasks.length === 0 ? (
        <p className="mb-2 text-sm text-muted-foreground">No tasks under this activity yet. Add what is to be done below; each one you finish moves the bar.</p>
      ) : (
        <ul className="mb-2 grid gap-1">
          {row.tasks.map((t) => (
            <li key={t.id} className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5">
              <div className="min-w-0 flex-1">
                <div className={cn('text-sm', t.done && 'text-muted-foreground line-through')}>{t.text}</div>
                <div className="text-[11px] text-muted-foreground">{t.date}{t.done && t.done_at ? ` - done ${t.done_at}${t.done_by_name ? ` by ${t.done_by_name}` : ''}` : ''}</div>
              </div>
              {can && (
                <Button size="sm" variant={t.done ? 'ghost' : 'outline'} loading={tick.isPending && tick.variables?.id === t.id} onClick={() => tick.mutate({ id: t.id, done: !t.done })}>
                  {t.done ? 'Undo' : 'Done'}
                </Button>
              )}
              {can && <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" aria-label={`Remove ${t.text}`} onClick={() => remove.mutate(t.id)}><Trash2 /></Button>}
            </li>
          ))}
        </ul>
      )}

      {can && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate() }}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="A task under this activity" maxLength={300} aria-label="New task under this activity" className="min-w-52 flex-1" />
          <Input type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} aria-label="Day for the task" className="w-40" />
          <Button type="submit" size="sm" disabled={!text.trim()} loading={add.isPending}><Plus /> Add task</Button>
        </form>
      )}
      {can && row.editable && row.tasks_total === 0 && <ProgressControl id={row.id} percent={row.actual_percent} updatedOn={row.updated_on} updatedBy={row.updated_by} />}
      {!row.editable && <p className="mt-2 text-[11px] text-muted-foreground">Its progress comes from the measurement book, so ticking tasks does not move the bar.</p>}
    </div>
  )
}
