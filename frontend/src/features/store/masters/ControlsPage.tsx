import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Field, Input } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { storeGet, storePut } from '@/api/store'

interface Controls { books_locked_upto: string; max_backdate_days: number; separate_duties: boolean; updated_by: string; updated_at: string; can_edit: boolean }
const KEY = ['store', 'masters', 'controls']

/** The company's controls on the store books: the day they are closed up to, how far back a document may be dated, and
 * whether staff may approve what they made themselves. */
export default function ControlsPage() {
  const q = useQuery({ queryKey: KEY, queryFn: () => storeGet<Controls>('masters', '/controls') })
  const [f, setF] = useState({ books_locked_upto: '', max_backdate_days: '30', separate_duties: true })
  useEffect(() => {
    if (q.data) setF({ books_locked_upto: q.data.books_locked_upto, max_backdate_days: String(q.data.max_backdate_days), separate_duties: q.data.separate_duties })
  }, [q.data])
  const save = useAction(
    () => storePut<Controls>('masters', '/controls', { ...f, max_backdate_days: Number(f.max_backdate_days) || 0 }),
    { invalidate: [KEY], success: 'Store controls saved' },
  )
  if (q.isPending) return <p className="text-sm text-muted-foreground">Loading...</p>
  if (q.isError || !q.data) return <p role="alert" className="text-sm text-danger">Could not load the store controls.</p>
  const edit = q.data.can_edit
  return (
    <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid max-w-2xl gap-5 rounded-xl border border-border bg-card p-5">
      <div>
        <h2 className="text-base font-semibold">Store controls</h2>
        <p className="text-sm text-muted-foreground">Apply to every store of the company.{q.data.updated_by ? ` Last changed by ${q.data.updated_by}.` : ''}{!edit ? ' Only the account holder or a store administrator can change them.' : ''}</p>
      </div>
      <Field label="Books closed up to" htmlFor="c-lock" hint="Nothing can be dated on or before this day, and nothing dated then can be cancelled - correct it with a new document instead. Leave empty to keep the books open.">
        <Input id="c-lock" type="date" disabled={!edit} value={f.books_locked_upto} onChange={(e) => setF((x) => ({ ...x, books_locked_upto: e.target.value }))} className="w-48" />
      </Field>
      <Field label="Back-dating allowed (days)" htmlFor="c-days" hint="How far back a receipt, issue, transfer, count or write-off may be dated. 0 means no limit. Opening stock is not limited.">
        <Input id="c-days" inputMode="numeric" disabled={!edit} value={f.max_backdate_days} onChange={(e) => setF((x) => ({ ...x, max_backdate_days: e.target.value.replace(/\D/g, '') }))} className="w-32" />
      </Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" disabled={!edit} checked={f.separate_duties} onChange={(e) => setF((x) => ({ ...x, separate_duties: e.target.checked }))} />
        <span><span className="font-medium">Someone else approves</span> - staff cannot approve a receipt, issue, transfer, count, write-off or return they made or submitted themselves. (The account holder can always approve; direct issues under their own right are allowed.)</span>
      </label>
      {edit && <div className="flex justify-end"><Button type="submit" loading={save.isPending}>Save</Button></div>}
    </form>
  )
}
