import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRightLeft, Archive } from 'lucide-react'
import { Badge, Button, Card, Field, Input, Modal, Select } from '@/components/ui'
import { get, post, ApiError } from '@/lib/api'
import { formatDate, formatQty, today } from '@/lib/format'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Cutover { cutover_date: string; done_by_name: string; done_at: string; carried: { store: string; opening: string; lines: number; value: number }[] }
interface OldItem { item_code: string; item_name: string; uom: string; on_hand: number; rate: number; value: number; problem: string }
interface OldStore { name: string; items: OldItem[]; value: number; problems: number; suggested_store_id: number | null }
interface Preview { done: Cutover | null; stores: OldStore[]; hub_stores: { id: number; code: string; name: string }[]; problems: string[] }

const KEY = ['store', 'cutover'] as const
/** Whether the company's old store has moved into the Hub - asked by the Hub's front page and the old screens. */
export const useCutover = () => useQuery({ queryKey: [...KEY, 'brief'], staleTime: 60_000, queryFn: async () => (await get<{ done: Cutover | null }>('/api/stock/cutover?brief=true')).done })

/** The old store's screens, kept at their new addresses. */
export const OLD_SCREENS = [
  { label: 'Stock & Issues', path: '/store/old/stock' },
  { label: 'Goods Receipt & Match', path: '/store/old/goods-receipt' },
  { label: 'Material Issue Voucher', path: '/store/old/material-vouchers' },
  { label: 'Material Used vs Costed', path: '/store/old/material-costing' },
]

/** On the Hub's front page: the old store, and - until it has moved - the way to move it. */
export function OldStoreCard() {
  const { can } = useSession()
  const done = useCutover()
  const [open, setOpen] = useState(false)
  if (done.isPending) return null
  const moved = done.data
  return (
    <Card className="mb-6 p-5">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            {moved ? <Archive className="size-4 text-muted-foreground" /> : <ArrowRightLeft className="size-4 text-primary" />}
            {moved ? 'Old store records' : 'Move the old store into the Hub'}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {moved
              ? `The old store moved into the Hub on ${formatDate(moved.cutover_date)}. Its receipts, issues and vouchers are kept here to read; new ones are made in the Hub.`
              : 'The old Stock & Issues and Goods Receipt screens still keep their own stock. Moving carries what each old store holds into a Hub store as opening stock, at its own rate, and keeps the old screens as records. Project costs keep counting the old issues.'}
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {OLD_SCREENS.map((s) => <Link key={s.path} to={s.path} className="text-primary hover:underline">{s.label}</Link>)}
          </div>
        </div>
        {!moved && can('store.admin') && <Button onClick={() => setOpen(true)}><ArrowRightLeft /> Move it now</Button>}
      </div>
      <Modal open={open} onOpenChange={(o) => !o && setOpen(false)} size="xl" title="Move the old store into the Hub"
        description="Once only. Each old store's closing stock becomes posted opening stock in the Hub store you choose, as on the date below. After this the old store takes no new receipts, issues or transfers.">
        {open && <MoveForm onDone={() => setOpen(false)} />}
      </Modal>
    </Card>
  )
}

function MoveForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const preview = useQuery({ queryKey: [...KEY, 'preview'], staleTime: 0, queryFn: () => get<Preview>('/api/stock/cutover') })
  const [on, setOn] = useState(today())
  const [into, setInto] = useState<Record<string, number | null>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (preview.isPending) return <p className="text-sm text-muted-foreground">Reading the old store...</p>
  if (preview.isError || !preview.data) return <p className="text-sm text-danger">The old store could not be read. Try again.</p>
  const p = preview.data
  const target = (s: OldStore) => (s.name in into ? into[s.name] : s.suggested_store_id)
  const ready = p.problems.length === 0 && p.stores.every((s) => target(s))
  const move = async () => {
    setBusy(true)
    setError('')
    try {
      const out = await post<{ message: string }>('/api/stock/cutover', { cutover_date: on, stores: Object.fromEntries(p.stores.map((s) => [s.name, target(s)])) })
      await qc.invalidateQueries({ queryKey: ['store'] })
      toast.success(out.message)
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The old store could not be moved. Try again.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid gap-4">
      {p.problems.length > 0 && (
        <div role="alert" className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-[13px]">
          <p className="mb-1 flex items-center gap-2 font-medium"><AlertTriangle className="size-4 text-warning" /> Put these right first</p>
          <ul className="list-disc pl-5">{p.problems.slice(0, 12).map((x) => <li key={x}>{x}</li>)}</ul>
          {p.problems.length > 12 && <p className="mt-1 text-muted-foreground">and {p.problems.length - 12} more</p>}
        </div>
      )}
      {p.stores.length === 0 ? <p className="text-sm text-muted-foreground">The old store holds nothing. Moving only closes it for new entries.</p> : p.stores.map((s) => (
        <div key={s.name} className="rounded-lg border border-border">
          <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-3 py-2">
            <p className="text-sm font-medium">{s.name}</p>
            <span className="text-xs text-muted-foreground">{s.items.length} items · {formatINR(s.value)}</span>
            {s.problems > 0 && <Badge tone="warning">{s.problems} to put right</Badge>}
            <div className="ml-auto w-64">
              <Select aria-label={`Hub store for ${s.name}`} value={target(s) ?? ''} placeholder="Choose the Hub store"
                onChange={(e) => setInto((x) => ({ ...x, [s.name]: Number(e.target.value) || null }))}
                options={p.hub_stores.map((h) => ({ value: h.id, label: `${h.code} · ${h.name}` }))} />
            </div>
          </div>
          <div className="max-h-56 overflow-auto">
            <table className="w-full text-[13px]">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-1.5">Item</th><th className="px-3 py-1.5 text-right">Held</th><th className="px-3 py-1.5 text-right">Rate</th><th className="px-3 py-1.5 text-right">Value</th></tr></thead>
              <tbody>{s.items.map((r) => (
                <tr key={r.item_code} className="border-t border-border">
                  <td className="px-3 py-1.5">{r.item_name || r.item_code}<div className="text-xs text-muted-foreground">{r.item_code}</div>{r.problem && <div className="text-xs text-danger">{r.problem}</div>}</td>
                  <td className="px-3 py-1.5 text-right tabular">{formatQty(r.on_hand)} {r.uom}</td>
                  <td className="px-3 py-1.5 text-right tabular">{formatINR(r.rate)}</td>
                  <td className="px-3 py-1.5 text-right tabular">{formatINR(r.value)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      ))}
      {p.hub_stores.length === 0 && <p className="text-sm text-danger">There is no Hub store yet. Add one under Masters first.</p>}
      <div className="flex flex-wrap items-end justify-end gap-3 border-t border-border pt-4">
        {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
        <Field label="Opening stock as on" htmlFor="co-date"><Input id="co-date" type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button loading={busy} disabled={!ready || !on} onClick={() => void move()}><ArrowRightLeft /> Move into the Hub</Button>
      </div>
    </div>
  )
}

/** Above an old store screen once the store has moved: say it is a record, and where the work is done now. */
export function OldStoreBanner({ hub }: { hub: string }) {
  const done = useCutover()
  if (!done.data) return null
  return (
    <p role="status" className="mb-4 flex flex-wrap items-center gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[13px]">
      <Archive className="size-4 text-warning" /> The old store moved into the Store Hub on {formatDate(done.data.cutover_date)}. This is its record; nothing new can be entered here.
      <Link to={hub} className="font-medium text-primary hover:underline">Go to the Store Hub</Link>
    </p>
  )
}
