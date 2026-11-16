import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, ShoppingCart, TriangleAlert } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { cn } from '@/lib/utils'
import { lowKeys, raiseLow, type LowRow, type RaiseAnswer } from './api'

const n = (v: string | number) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const key = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`)

/** Raise an indent or an enquiry for the low items ticked. Requested quantities start at what the server says to order (the suggested
 * quantity less what is already coming) and can be changed; the server checks every line again against the stock as it is now. */
export function RaiseLowStock({ rows, canIndent, canEnquire, onClose }: { rows: LowRow[]; canIndent: boolean; canEnquire: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const projects = useProjects()
  const [action, setAction] = useState<'INDENT' | 'ENQUIRY'>(canIndent ? 'INDENT' : 'ENQUIRY')
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(rows.map((r) => [r.key, Number(r.to_order) > 0 ? r.to_order : r.suggested_qty])))
  const [f, setF] = useState({ project_id: 0, required_by: '', title: '' })
  const [answer, setAnswer] = useState<RaiseAnswer | null>(null)
  // One key for one press of the button: a second click, a retry or a double submit raises nothing twice.
  const submission = useRef(key())
  const lineOf = (r: LowRow) => ({ store_id: r.store_id, item_id: r.item_id, qty: qty[r.key] ?? '', alert_id: r.alert_id })
  const needsProject = action === 'INDENT' && rows.some((r) => !r.project_id) && !f.project_id
  const bad = rows.filter((r) => !(Number(qty[r.key]) > 0))

  const send = useAction(() => raiseLow({ action, lines: rows.map(lineOf), request_key: submission.current, project_id: f.project_id || undefined, required_by: f.required_by, title: f.title.trim() || undefined }),
    {
      success: false,
      onSuccess: (a) => { setAnswer(a); void qc.invalidateQueries({ queryKey: lowKeys.all }) },
    })
  const byItem = (r: LowRow) => answer?.results.find((x) => x.store_id === r.store_id && x.item_id === r.item_id)
  // After a partial answer the key is renewed, so the lines that failed can be corrected and raised as a new request.
  const again = () => { submission.current = key(); setAnswer(null) }

  return (
    <Modal open onOpenChange={(o) => !o && !send.isPending && onClose()} size="xl" title="Raise indent / enquiry for the selected materials"
      description="The quantity to order starts at the suggested reorder quantity, less what is already on an open enquiry or order. Change what is needed; every line is checked again against the stock as it is now."
      footer={answer ? (
        <>
          {answer.failed > 0 && answer.raised >= 0 && <Button variant="outline" onClick={again}>Correct and try again</Button>}
          <Button onClick={onClose}>Done</Button>
        </>
      ) : (
        <>
          <Button variant="ghost" onClick={onClose} disabled={send.isPending}>Cancel</Button>
          <Button onClick={() => send.mutate()} loading={send.isPending} disabled={send.isPending || !rows.length || bad.length > 0 || needsProject}>
            <ShoppingCart /> {action === 'INDENT' ? 'Raise indent' : 'Raise enquiry'} for {rows.length} material{rows.length === 1 ? '' : 's'}
          </Button>
        </>
      )}>
      {answer && (
        <div role="status" className={cn('mb-4 rounded-lg border p-3 text-sm', answer.failed ? 'border-warning/40 bg-warning-soft' : 'border-success/30 bg-success-soft')}>
          <p className="flex items-center gap-2 font-medium">{answer.failed ? <TriangleAlert className="size-4 text-warning" aria-hidden /> : <CheckCircle2 className="size-4 text-success" aria-hidden />}{answer.message}</p>
          {answer.created.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {answer.created.map((c) => (
                <li key={`${c.type}-${c.id}`}>
                  {c.type === 'INDENT' ? 'Indent' : 'Enquiry'} <strong>{c.number}</strong> - {c.lines} line{c.lines === 1 ? '' : 's'}{c.store_code ? ` in ${c.store_code}` : ''}{c.type === 'INDENT' ? ', waiting for approval' : ''}{' '}
                  <Link className="text-primary underline-offset-4 hover:underline" to={c.type === 'INDENT' ? `/store/hub/outward/indent/${c.id}` : `/store/enquiries/${c.id}`} onClick={onClose}>Open</Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1.5 text-xs text-muted-foreground">The alerts stay open until the stock is back above the reorder level. Raising an indent or enquiry does not add stock.</p>
        </div>
      )}
      {!answer && (
        <div className="mb-4 grid gap-3 sm:grid-cols-4">
          <Field label="Raise" htmlFor="rl-action" className="sm:col-span-1">
            <Select id="rl-action" value={action} onChange={(e) => setAction(e.target.value as 'INDENT' | 'ENQUIRY')}
              options={[{ value: 'INDENT', label: 'Indent (for approval)', disabled: !canIndent }, { value: 'ENQUIRY', label: 'Purchase enquiry', disabled: !canEnquire }]} />
          </Field>
          <Field label={action === 'INDENT' ? 'Project (where a store has none)' : 'Project'} htmlFor="rl-proj" className="sm:col-span-2">
            <Select id="rl-proj" value={f.project_id || ''} placeholder="The store's own project" onChange={(e) => setF({ ...f, project_id: Number(e.target.value) || 0 })}
              options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} />
          </Field>
          <Field label="Needed by" htmlFor="rl-need"><Input id="rl-need" type="date" min={today()} value={f.required_by} onChange={(e) => setF({ ...f, required_by: e.target.value })} /></Field>
          {action === 'ENQUIRY' && <Field label="Enquiry title" htmlFor="rl-title" className="sm:col-span-4"><Input id="rl-title" maxLength={120} placeholder="Low stock" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>}
        </div>
      )}
      {needsProject && !answer && <p role="alert" className="mb-3 text-sm text-warning">One of these stores belongs to no project, so choose the project the indent is for.</p>}
      <div className="max-h-[22rem] overflow-auto rounded-lg border border-border">
        <table className="w-full min-w-max text-[13px]">
          <thead className="sticky top-0 z-10 bg-surface text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-2.5 py-2">Material</th><th className="px-2.5 py-2">Code</th><th className="px-2.5 py-2">Project</th><th className="px-2.5 py-2">Store</th>
              <th className="px-2.5 py-2 text-right">Available</th><th className="px-2.5 py-2 text-right">Reorder level</th><th className="px-2.5 py-2 text-right">Suggested</th>
              <th className="px-2.5 py-2 text-right">Requested</th><th className="px-2.5 py-2">Unit</th>{answer && <th className="px-2.5 py-2">Result</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const res = byItem(r)
              return (
                <tr key={r.key} className={cn('border-t border-border align-top', res && !res.ok && 'bg-danger-soft/40', res?.ok && 'bg-success-soft/40')}>
                  <td className="px-2.5 py-2 font-medium">{r.item_name}</td>
                  <td className="px-2.5 py-2 font-mono text-xs">{r.item_code}</td>
                  <td className="px-2.5 py-2">{r.project || <span className="text-muted-foreground">-</span>}</td>
                  <td className="px-2.5 py-2">{r.store_code}<div className="text-xs text-muted-foreground">{r.store_name}</div></td>
                  <td className="px-2.5 py-2 text-right tabular-nums text-danger">{n(r.available)}{Number(r.on_hand) !== Number(r.available) && <div className="text-[11px] text-muted-foreground" title="On hand, before what is on hold, rejected, expired or reserved for approved indents">{n(r.on_hand)} on hand</div>}</td>
                  <td className="px-2.5 py-2 text-right tabular-nums">{n(r.reorder_level)}</td>
                  <td className="px-2.5 py-2 text-right tabular-nums" title={r.suggest_basis}>{n(r.suggested_qty)}{Number(r.on_order) > 0 && <div className="text-[11px] text-muted-foreground">{n(r.on_order)} coming</div>}</td>
                  <td className="px-2.5 py-2 text-right">
                    <Input aria-label={`Requested quantity of ${r.item_name} in ${r.store_code}`} inputMode="decimal" className="h-8 w-28 text-right" value={qty[r.key] ?? ''} disabled={!!answer || send.isPending}
                      aria-invalid={!(Number(qty[r.key]) > 0)} onChange={(e) => setQty({ ...qty, [r.key]: e.target.value })} />
                  </td>
                  <td className="px-2.5 py-2">{r.base_uom}</td>
                  {answer && <td className={cn('max-w-xs px-2.5 py-2 text-xs', res?.ok ? 'text-success' : 'text-danger')}>{res ? `${res.ok ? 'Raised: ' : 'Not raised: '}${res.message}` : '-'}</td>}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!answer && bad.length > 0 && <p role="alert" className="mt-2 text-xs text-danger">Give every material a quantity above zero, or untick it on the list.</p>}
    </Modal>
  )
}
