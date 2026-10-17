import { useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Printer } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { Badge, Button, Card, SkeletonRows } from '@/components/ui'
import { apiUrl } from '@/lib/api'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storeGet, storePerm, storePost, type DocStatus } from '@/api/store'
import { DocActionsBar, DocStatusBadge } from '../shared'
import type { DocAction } from '../shared/DocActionsBar'
import { errText, type ControlMeta, type LogRow } from './types'

export type Kind = 'transfers' | 'counts' | 'adjustments' | 'scrap'
const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '')

export function History({ log }: { log: LogRow[] }) {
  return (
    <Card className="p-5">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ul className="space-y-1 text-sm">{log.map((l, i) => <li key={i}><Badge>{l.to}</Badge> <span className="text-muted-foreground">{l.user} · {when(l.at)}{l.note && !l.note.startsWith('Created') ? ` · ${l.note}` : ''}</span></li>)}</ul>
    </Card>
  )
}

/** Loads one control document and runs its submit / approve / post / cancel actions. */
export function useControlDoc<T extends { status: DocStatus }>(kind: Kind) {
  const { id } = useParams()
  const qc = useQueryClient()
  const { can } = useSession()
  const q = useQuery({ queryKey: ['store', 'control', kind, id], queryFn: () => storeGet<T>('control', `/${kind}/${id}`) })
  const [busy, setBusy] = useState<DocAction | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['store'] })
  const act = async (a: DocAction, reason?: string) => {
    setBusy(a)
    try {
      await storePost('control', `/${kind}/${id}/${a}`, { reason: reason ?? '' })
      toast.success(a === 'post' ? 'Posted' : a === 'cancel' ? 'Cancelled' : a === 'submit' ? 'Submitted' : 'Approved')
      await refresh()
    } catch (e) { toast.error(errText(e)); throw e } finally { setBusy(null) }
  }
  const rights = { submit: can(storePerm('control', 'create')), approve: can(storePerm('control', 'approve')), post: can(storePerm('control', 'post')), cancel: can(storePerm('control', 'cancel')) }
  return { id, q, busy, act, rights, can, refresh }
}

/** Title, status, print link, the action bar and the history, around a document's own body. */
export function DocShell({ kind, id, number, sub, status, extra, actions, children, cancelReason, log, busy, act, rights, prints }: {
  prints?: { label: string; form: string }[]
  kind: Kind; id: number; number: string; sub: ReactNode; status: DocStatus; extra?: ReactNode; actions?: ReactNode; children: ReactNode; cancelReason: string; log: LogRow[]
  busy: DocAction | null; act: (a: DocAction, reason?: string) => Promise<void>; rights: Partial<Record<DocAction, boolean>>
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold">{number}</h2><div className="text-sm text-muted-foreground">{sub}</div></div>
        <div className="flex flex-wrap items-center gap-2">
          {extra}<DocStatusBadge status={status} />
          {(prints ?? [{ label: 'Print', form: '' }]).map((p) => (
            <a key={p.form} href={apiUrl(`/api/store/control/${kind}/${id}/pdf${p.form ? `?form=${p.form}` : ''}`)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Printer /> {p.label}</Button></a>
          ))}
        </div>
      </div>
      <DocActionsBar status={status} can={rights} busy={busy} onAction={act} />
      {actions}
      {status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {cancelReason}</p>}
      {children}
      <History log={log} />
    </div>
  )
}

export const useControlMeta = () => useQuery({ queryKey: ['store', 'control', 'meta'], staleTime: 60 * 60_000, queryFn: () => storeGet<ControlMeta>('control', '/meta') })

export function Loading() { return <SkeletonRows rows={6} cols={4} /> }
