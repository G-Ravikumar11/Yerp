import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { Badge, Button, Input, Select } from '@/components/ui'
import { useRegister } from '@/api/equipment'
import { STATUS_LABEL, statusTone, usePeople } from '@/api/plant'
import type { ServiceStatus } from '@/api/equipment'

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)} dot>{STATUS_LABEL[status] ?? status}</Badge>
}

/** Where a machine stands on its service schedule. */
const TONE: Record<ServiceStatus, 'success' | 'danger' | 'warning' | 'neutral' | 'info'> = {
  Overdue: 'danger', 'Service due': 'danger', 'Due soon': 'warning', Upcoming: 'success', Incomplete: 'neutral', 'Not scheduled': 'neutral',
}
export function ServiceBadge({ status }: { status: ServiceStatus }) {
  return <Badge tone={TONE[status] ?? 'neutral'} dot>{status}</Badge>
}

/** A date range, the same on every tab. */
export function RangeBar({ from, to, onChange, children }: { from: string; to: string; onChange: (from: string, to: string) => void; children?: React.ReactNode }) {
  return (
    <div role="search" className="mb-3 flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">From<Input type="date" aria-label="From date" className="w-36" value={from} max={to || undefined} onChange={(e) => onChange(e.target.value, to)} /></label>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">To<Input type="date" aria-label="To date" className="w-36" value={to} min={from || undefined} onChange={(e) => onChange(from, e.target.value)} /></label>
      {children}
      {(from || to) && <Button size="sm" variant="ghost" onClick={() => onChange('', '')}><X /> Clear dates</Button>}
    </div>
  )
}

/** Page through a long list, 25 at a time. */
export function usePaged<T>(rows: readonly T[] | undefined, size = 25) {
  const [page, setPage] = useState(1)
  const list = rows ?? []
  const pages = Math.max(1, Math.ceil(list.length / size))
  const p = Math.min(page, pages)
  const shown = useMemo(() => list.slice((p - 1) * size, p * size), [list, p, size])
  const pager = list.length > size ? (
    <nav aria-label="Pages" className="flex items-center justify-between px-4 py-2 text-xs text-muted-foreground">
      <span>{(p - 1) * size + 1}-{Math.min(list.length, p * size)} of {list.length}</span>
      <span className="flex items-center gap-1.5"><Button size="sm" variant="outline" aria-label="Previous page" disabled={p <= 1} onClick={() => setPage(p - 1)}><ChevronLeft /></Button>Page {p} of {pages}<Button size="sm" variant="outline" aria-label="Next page" disabled={p >= pages} onClick={() => setPage(p + 1)}><ChevronRight /></Button></span>
    </nav>
  ) : <p className="px-4 py-2 text-xs text-muted-foreground">{list.length} {list.length === 1 ? 'record' : 'records'}</p>
  return { shown, pager }
}

/** A machine from the register (not archived). `filter` narrows it - only rented machines, say. */
export function MachineSelect({ id, value, onChange, filter, placeholder = 'Choose the machine', emptyText }: { id: string; value: number; onChange: (id: number) => void; filter?: (m: { ownership: string; status: string }) => boolean; placeholder?: string; emptyText?: string }) {
  const q = useRegister('')
  const rows = (q.data?.assets ?? []).filter((m) => m.status !== 'Disposed' && (!filter || filter(m)))
  return <Select id={id} value={value || ''} placeholder={q.isPending ? 'Loading...' : emptyText && !rows.length ? emptyText : placeholder} onChange={(e) => onChange(Number(e.target.value) || 0)} options={rows.map((m) => ({ value: m.id, label: `${m.code} ${m.name} - ${STATUS_LABEL[m.status] ?? m.status}` }))} />
}

/** An employee from HR - the plant screens keep no people of their own. */
export function PersonSelect({ id, value, onChange, placeholder = 'Choose the employee' }: { id: string; value: number; onChange: (id: number) => void; placeholder?: string }) {
  const q = usePeople()
  return <Select id={id} value={value || ''} placeholder={q.isPending ? 'Loading...' : placeholder} onChange={(e) => onChange(Number(e.target.value) || 0)} options={(q.data?.employees ?? []).map((p) => ({ value: p.id, label: `${p.name}${p.code ? ` (${p.code})` : ''}${p.designation ? ` - ${p.designation}` : ''}` }))} />
}

export function FormFoot({ error, busy, label, onClose, onSave }: { error?: string; busy: boolean; label: string; onClose: () => void; onSave: () => void }) {
  return (
    <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
      {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button loading={busy} disabled={busy} onClick={onSave}>{label}</Button>
    </div>
  )
}

export const LoadError = ({ message, retry }: { message: string; retry: () => void }) => (
  <div role="alert" className="flex items-center gap-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger"><span className="flex-1">{message || 'This could not be loaded.'}</span><Button size="sm" variant="outline" onClick={retry}>Try again</Button></div>
)
