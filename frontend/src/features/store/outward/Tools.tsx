import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storePerm, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker } from '../shared'

interface Tool {
  id: number; item_id: number; item_code: string; item_name: string; store_id: number; store_code: string; serial_no: string
  status: 'AVAILABLE' | 'ISSUED' | 'IN_SERVICE' | 'LOST' | 'RETIRED'; condition: 'GOOD' | 'DAMAGED'; holder_name: string
  due_back: string; overdue_days: number; last_service: string; next_service: string; service_due: boolean; notes: string
  events?: { event: string; condition: string; holder: string; note: string; by: string; at: string }[]
}

const KEY = ['store', 'tools'] as const
const TONE = { AVAILABLE: 'success', ISSUED: 'info', IN_SERVICE: 'warning', LOST: 'danger', RETIRED: 'neutral' } as const
const LABEL = { AVAILABLE: 'In store', ISSUED: 'Out', IN_SERVICE: 'In service', LOST: 'Lost', RETIRED: 'Retired' } as const
const dmy = (iso: string) => (iso ? new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
const today = () => new Date().toLocaleDateString('en-CA')

/** Tools by serial number: who has each, what shape it is in, when it is next serviced - and a reminder for what is overdue. */
export default function Tools() {
  const { can } = useSession()
  const canEdit = can(storePerm('outward', 'create'))
  const [f, setF] = useState({ status: '', store_id: 0, q: '' })
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const params = new URLSearchParams()
  if (f.status) params.set('status', f.status)
  if (f.store_id) params.set('store_id', String(f.store_id))
  if (f.q.trim()) params.set('q', f.q.trim())
  const rows = useQuery({ queryKey: [...KEY, f], queryFn: () => get<{ items: Tool[] }>(`/api/store/tools?${params}`) })
  const remind = useAction(() => post<{ mentioned: number }>('/api/store/tools/remind'), { invalidate: [['dashboard']], success: (r) => (r.mentioned ? `${r.mentioned} reminder${r.mentioned === 1 ? '' : 's'} sent` : 'Nothing new to chase') })
  const columns: TableColumn<Tool>[] = [
    { id: 'tool', header: 'Tool', sort: (t) => t.item_name, cell: (t) => <div><div className="font-medium">{t.item_name}</div><div className="font-mono text-xs text-muted-foreground">{t.serial_no}</div></div> },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'md', cell: (t) => <span className="font-mono text-[13px]">{t.store_code}</span> },
    { id: 'status', header: 'Status', width: '9rem', cell: (t) => <Badge tone={TONE[t.status]} dot>{LABEL[t.status]}</Badge> },
    { id: 'who', header: 'Held by', hideBelow: 'sm', cell: (t) => (t.holder_name ? <span>{t.holder_name}{t.due_back && <span className={t.overdue_days ? 'text-danger' : 'text-muted-foreground'}> - back {dmy(t.due_back)}{t.overdue_days ? ` (${t.overdue_days}d late)` : ''}</span>}</span> : '-') },
    { id: 'cond', header: 'Condition', width: '8rem', hideBelow: 'md', cell: (t) => (t.condition === 'DAMAGED' ? <span className="text-danger">Damaged</span> : 'Good') },
    { id: 'svc', header: 'Next service', width: '9rem', hideBelow: 'lg', cell: (t) => (t.next_service ? <span className={t.service_due ? 'text-warning' : ''}>{dmy(t.next_service)}</span> : '-') },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="tl-store" className="w-52"><StorePicker id="tl-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => setF((x) => ({ ...x, store_id: id ?? 0 }))} /></Field>
        <Field label="Status" htmlFor="tl-status" className="w-40">
          <Select id="tl-status" value={f.status} placeholder="Any" onChange={(e) => setF((x) => ({ ...x, status: e.target.value }))} options={Object.entries(LABEL).map(([v, l]) => ({ value: v, label: l }))} />
        </Field>
        <Field label="Search" htmlFor="tl-q" className="w-52"><Input id="tl-q" value={f.q} onChange={(e) => setF((x) => ({ ...x, q: e.target.value }))} placeholder="Tool, serial or holder" /></Field>
        {canEdit && <div className="ml-auto flex gap-2"><Button variant="outline" loading={remind.isPending} onClick={() => remind.mutate()}>Send reminders now</Button><Button onClick={() => setAdding(true)}><Plus /> Add tool</Button></div>}
      </div>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the tools.</p> : (
        <DataTable label="Tools" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(t) => t.id} onRowClick={(t) => setOpen(t.id)} empty="No tools in the register. Add each tool by its serial number." />
      )}
      {adding && <AddModal onClose={() => setAdding(false)} />}
      {open != null && <ToolModal id={open} canEdit={canEdit} onClose={() => setOpen(null)} />}
    </div>
  )
}

function AddModal({ onClose }: { onClose: () => void }) {
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const [storeId, setStoreId] = useState(0)
  const [f, setF] = useState({ serial_no: '', next_service: '', notes: '' })
  const save = useAction(() => post<Tool>('/api/store/tools', { item_id: item?.id, store_id: storeId, ...f, next_service: f.next_service || null }), { invalidate: [[...KEY]], success: 'Tool added', onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Add a tool" description="Only items set up as a tool or a returnable can be kept in the register.">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <Field label="Item" htmlFor="at-item"><ItemPicker id="at-item" value={item} onChange={setItem} /></Field>
        <Field label="Kept in" htmlFor="at-store"><StorePicker id="at-store" value={storeId || null} placeholder="Choose the store" onChange={(id) => setStoreId(id ?? 0)} /></Field>
        <Field label="Serial number" htmlFor="at-serial"><Input id="at-serial" value={f.serial_no} onChange={(e) => setF({ ...f, serial_no: e.target.value })} maxLength={60} /></Field>
        <Field label="Next service due" htmlFor="at-svc" hint="Optional."><Input id="at-svc" type="date" value={f.next_service} onChange={(e) => setF({ ...f, next_service: e.target.value })} /></Field>
        <Field label="Notes" htmlFor="at-notes"><Input id="at-notes" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} maxLength={200} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!item || !storeId || !f.serial_no.trim()}>Add tool</Button>
        </div>
      </form>
    </Modal>
  )
}

function ToolModal({ id, canEdit, onClose }: { id: number; canEdit: boolean; onClose: () => void }) {
  const q = useQuery({ queryKey: [...KEY, 'one', id], queryFn: () => get<Tool>(`/api/store/tools/${id}`) })
  const [f, setF] = useState({ holder_name: '', due_back: '', condition: 'GOOD', next_service: '', note: '' })
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }))
  const run = useAction(({ action, body }: { action: string; body: Record<string, unknown> }) => post<Tool>(`/api/store/tools/${id}/${action}`, body), {
    invalidate: [[...KEY]], success: 'Saved', onSuccess: () => setF({ holder_name: '', due_back: '', condition: 'GOOD', next_service: '', note: '' }),
  })
  const t = q.data
  const go = (action: string, body: Record<string, unknown> = {}) => run.mutate({ action, body: { note: f.note, ...body } })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={t ? `${t.item_name} - ${t.serial_no}` : 'Tool'} description={t ? `${LABEL[t.status]}${t.holder_name ? ` with ${t.holder_name}` : ''}. ${t.condition === 'DAMAGED' ? 'Damaged.' : 'In good condition.'}` : undefined}>
      {!t ? <p className="text-sm text-muted-foreground">Loading...</p> : (
        <div className="grid gap-5">
          {canEdit && t.status !== 'RETIRED' && (
            <div className="grid gap-3 rounded-lg border border-border p-3">
              {t.status === 'AVAILABLE' && (
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto] sm:items-end">
                  <Field label="Give to" htmlFor="tm-who"><Input id="tm-who" value={f.holder_name} onChange={(e) => set('holder_name', e.target.value)} placeholder="Name of who takes it" maxLength={80} /></Field>
                  <Field label="Due back" htmlFor="tm-due"><Input id="tm-due" type="date" min={today()} value={f.due_back} onChange={(e) => set('due_back', e.target.value)} /></Field>
                  <Button loading={run.isPending} disabled={!f.holder_name.trim()} onClick={() => go('assign', { holder_name: f.holder_name, due_back: f.due_back || null })}>Give out</Button>
                </div>
              )}
              {t.status === 'ISSUED' && (
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                  <Field label="Condition on return" htmlFor="tm-cond"><Select id="tm-cond" value={f.condition} onChange={(e) => set('condition', e.target.value)} options={[{ value: 'GOOD', label: 'Good' }, { value: 'DAMAGED', label: 'Damaged' }]} /></Field>
                  <Button loading={run.isPending} onClick={() => go('receive', { condition: f.condition })}>Take back</Button>
                </div>
              )}
              {t.status === 'IN_SERVICE' && (
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                  <Field label="Next service due" htmlFor="tm-next"><Input id="tm-next" type="date" value={f.next_service} onChange={(e) => set('next_service', e.target.value)} /></Field>
                  <Button loading={run.isPending} onClick={() => go('service-done', { next_service: f.next_service || null })}>Back from service</Button>
                </div>
              )}
              <Field label="Note" htmlFor="tm-note" hint="Required when it comes back damaged or is lost."><Input id="tm-note" value={f.note} onChange={(e) => set('note', e.target.value)} maxLength={200} /></Field>
              <div className="flex flex-wrap gap-2">
                {t.status === 'AVAILABLE' && <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => go('service-out')}>Send for service</Button>}
                {t.status !== 'LOST' && <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => go('lose')}>Mark lost</Button>}
                {t.status !== 'ISSUED' && <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => go('retire')}>Retire</Button>}
              </div>
            </div>
          )}
          <section>
            <h3 className="mb-2 border-b pb-1 text-sm font-semibold">History</h3>
            <ul className="divide-y rounded-lg border text-sm">
              {(t.events ?? []).map((e, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <span><span className="font-medium">{e.event.replace('_', ' ').toLowerCase()}</span>{e.holder && ` - ${e.holder}`}{e.note && <span className="text-muted-foreground"> - {e.note}</span>}</span>
                  <span className="text-xs text-muted-foreground">{e.by} {dmy(e.at)}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Modal>
  )
}
