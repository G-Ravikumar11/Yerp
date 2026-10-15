import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input } from '@/components/ui'
import { addTask, deleteTask, editTask, schKeys, type DayRow, type Placing } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { ProgressBar } from './ProgressBar'
import { ProgressControl } from './ProgressControl'

/**
 * One activity opened up: the tasks under it. Pressing Done on a task raises the activity's bar by that task's share
 * of it - the work is done a task at a time, and the bar is how many of them are.
 */
export type PanelRow = Pick<DayRow, 'id' | 'code' | 'name' | 'planned_start' | 'planned_finish' | 'planned_percent' | 'actual_percent' | 'tasks' | 'tasks_done' | 'tasks_total' | 'editable' | 'updated_on' | 'updated_by'> & Placing

export function ActivityPanel({ job, row, on, can, tone }: { job: number; row: PanelRow; on: string; can: boolean; tone: string }) {
  const [text, setText] = useState('')
  const [day, setDay] = useState(on)
  const add = useAction(() => addTask(job, { text: text.trim(), date: day, activity_id: row.id }), { invalidate: [schKeys.all], success: 'Task added', onSuccess: () => setText('') })
  const tick = useAction((v: { id: number; done: boolean }) => editTask(v.id, { done: v.done }), { invalidate: [schKeys.all] })
  // Only part of a task is done: say how much, and the activity's bar moves by that share of it.
  const [partly, setPartly] = useState<{ id: number; value: number } | null>(null)
  const shareOf = (t: PanelRow['tasks'][number]) => (partly?.id === t.id ? partly.value : t.done ? 100 : t.percent)
  const preview = row.tasks.length > 0 && partly ? row.tasks.reduce((sum, t) => sum + shareOf(t), 0) / row.tasks.length : row.actual_percent
  const part = useAction((v: { id: number; percent: number }) => editTask(v.id, { percent: v.percent }), { invalidate: [schKeys.all], success: 'Progress recorded', onSuccess: () => setPartly(null) })
  const remove = useAction((id: number) => deleteTask(id), { invalidate: [schKeys.all], success: 'Task removed' })
  return (
    <div className="rounded-lg border border-primary/40 bg-card p-3 shadow-card" aria-label={`Tasks of ${row.name}`}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          {row.path && <span className="block text-[11px] text-muted-foreground">{row.path}</span>}
          <span className="mr-2 font-mono text-xs text-muted-foreground">{row.wbs || row.code}</span>
          <span className="font-semibold">{row.name}</span>
          <span className="ml-2 text-[11px] text-muted-foreground">{row.planned_start} to {row.planned_finish}</span>
        </div>
        <span className="text-xs text-muted-foreground">{row.tasks_done} of {row.tasks_total} tasks done</span>
      </div>
      {/* While a percentage is being typed the bar already shows what the activity will be at. */}
      <ProgressBar percent={preview} planned={row.planned_percent} tone={tone} label={`${row.name} done`} className="mb-3" />

      {row.tasks.length === 0 ? (
        <p className="mb-2 text-sm text-muted-foreground">No tasks under this activity yet. Add what is to be done below; each one you finish moves the bar.</p>
      ) : (
        <ul className="mb-2 grid gap-1">
          {row.tasks.map((t) => {
            const part_done = !t.done && t.percent > 0
            const editing = partly?.id === t.id
            return (
              <li key={t.id} className="rounded-md border border-border px-2.5 py-1.5">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <div className={cn('text-sm', t.done && 'text-muted-foreground line-through')}>{t.text}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {t.date}
                      {t.done && t.done_at ? ` - done ${t.done_at}${t.done_by_name ? ` by ${t.done_by_name}` : ''}` : ''}
                      {part_done ? ` - ${t.percent}% done${t.done_by_name ? ` (${t.done_by_name})` : ''}` : ''}
                    </div>
                  </div>
                  {can && !editing && (
                    <div className="flex items-center gap-1.5">
                      {!t.done && <Button size="sm" variant="outline" onClick={() => setPartly({ id: t.id, value: t.percent > 0 ? t.percent : 50 })}>Partially</Button>}
                      <Button size="sm" variant={t.done ? 'ghost' : 'outline'} loading={tick.isPending && tick.variables?.id === t.id} onClick={() => tick.mutate({ id: t.id, done: !t.done })}>
                        {t.done ? 'Undo' : 'Done'}
                      </Button>
                      {part_done && <Button size="sm" variant="ghost" onClick={() => tick.mutate({ id: t.id, done: false })}>Reset</Button>}
                      <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" aria-label={`Remove ${t.text}`} onClick={() => remove.mutate(t.id)}><Trash2 /></Button>
                    </div>
                  )}
                </div>
                {(part_done || editing) && <ProgressBar thin percent={editing && partly ? partly.value : t.percent} tone="bg-warning" label={`${t.text} part done`} className="mt-1" />}
                {editing && partly && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2">
                    <span className="text-xs text-muted-foreground">How much of it is done?</span>
                    <label className="flex items-center gap-1 text-xs text-muted-foreground">
                      <input type="number" inputMode="numeric" min={0} max={100} step={1} value={partly.value} aria-label={`Percentage of ${t.text} done`} autoFocus
                        onChange={(e) => setPartly({ id: t.id, value: Math.max(0, Math.min(100, Math.round(Number(e.target.value) || 0))) })}
                        className="h-8 w-16 rounded-md border border-input bg-background px-2 text-right text-sm text-foreground tabular" />%
                    </label>
                    <input type="range" min={0} max={100} step={5} value={partly.value} aria-label={`How much of ${t.text} is done`} onChange={(e) => setPartly({ id: t.id, value: Number(e.target.value) })} className="h-2 min-w-32 flex-1 cursor-pointer accent-[var(--primary)]" />
                    <Button size="sm" loading={part.isPending} onClick={() => part.mutate({ id: t.id, percent: partly.value })}>Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setPartly(null)}>Cancel</Button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {can && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate() }}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="A task under this activity" maxLength={300} aria-label="New task under this activity" className="min-w-52 flex-1" />
          <Input type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} aria-label="Day for the task" className="w-40" />
          <Button type="submit" size="sm" disabled={!text.trim()} loading={add.isPending}><Plus /> Add task</Button>
        </form>
      )}
      {can && row.editable && row.tasks_total === 0 && <ProgressControl id={row.id} percent={row.actual_percent} updatedOn={row.updated_on} updatedBy={row.updated_by} quantity={row.quantity} uom={row.uom} qtyDone={row.qty_done} />}
      {!row.editable && <p className="mt-2 text-[11px] text-muted-foreground">Its progress comes from the measurement book, so ticking tasks does not move the bar.</p>}
    </div>
  )
}
