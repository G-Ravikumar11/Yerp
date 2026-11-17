import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { UserRound } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { ApiError, api, get } from '@/lib/api'
import { formatDate } from '@/lib/format'

export type FollowUpKind = 'ncr' | 'incident' | 'permit'
const LABEL: Record<FollowUpKind, string> = { ncr: 'NCR', incident: 'Incident', permit: 'Permit' }

interface Person { id: number; name: string; designation: string }
/** The staff a quality or safety item can be given to. */
export const useFollowUpPeople = (enabled = true) =>
  useQuery({ queryKey: ['follow-up', 'people'], enabled, staleTime: 5 * 60_000, queryFn: async () => (await get<{ people: Person[] }>('/api/follow-up/people')).people })

/**
 * Who on the staff sees an NCR, incident or permit through, and by when. They are reminded every day from the day
 * before it is due until it is closed. A permit is due when it runs out, so it takes only an owner.
 */
export function FollowUp({ kind, id, number, ownerId, due, open, canEdit, invalidate }: {
  kind: FollowUpKind; id: number; number: string; ownerId?: number | null; due?: string; open: boolean; canEdit: boolean; invalidate: readonly unknown[]
}) {
  const people = useFollowUpPeople(canEdit || !!ownerId)
  const [editing, setEditing] = useState(false)
  const owner = people.data?.find((p) => p.id === ownerId)
  return (
    <div className="text-[13px]">
      {ownerId ? <span className="inline-flex items-center gap-1"><UserRound className="size-3.5 text-muted-foreground" />{owner?.name ?? 'Owner set'}</span> : <span className="text-muted-foreground">No owner</span>}
      {kind !== 'permit' && due && <div className="text-xs text-muted-foreground">due {formatDate(due)}</div>}
      {open && canEdit && <button type="button" className="block text-xs text-primary underline-offset-2 hover:underline" onClick={() => setEditing(true)}>{ownerId ? 'Change' : 'Give it to somebody'}</button>}
      {editing && <FollowUpModal kind={kind} id={id} number={number} ownerId={ownerId} due={due} people={people.data ?? []} invalidate={invalidate} onClose={() => setEditing(false)} />}
    </div>
  )
}

function FollowUpModal({ kind, id, number, ownerId, due, people, invalidate, onClose }: {
  kind: FollowUpKind; id: number; number: string; ownerId?: number | null; due?: string; people: Person[]; invalidate: readonly unknown[]; onClose: () => void
}) {
  const qc = useQueryClient()
  const [who, setWho] = useState(ownerId ? String(ownerId) : '')
  const [date, setDate] = useState(due ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await api(`/api/follow-up/${kind}/${id}`, { method: 'PUT', body: { owner_id: who ? Number(who) : null, ...(kind === 'permit' ? {} : { due_date: date }) }, quiet: true })
      await qc.invalidateQueries({ queryKey: invalidate as unknown[] })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Not saved.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Who sees ${LABEL[kind]} ${number} through`}
      description={kind === 'permit' ? 'They are reminded every day once the permit has run out and is still not closed.' : 'They are told now, and reminded every day from the day before it is due until it is closed.'}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={() => void save()}>Save</Button></>}>
      <div className="grid gap-4">
        <Field label="Owner" htmlFor="fu-owner">
          <Select id="fu-owner" value={who} onChange={(e) => setWho(e.target.value)} options={[{ value: '', label: 'Nobody' }, ...people.map((p) => ({ value: String(p.id), label: p.designation ? `${p.name} - ${p.designation}` : p.name }))]} />
        </Field>
        {kind !== 'permit' && <Field label="Due date" htmlFor="fu-due"><Input id="fu-due" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>}
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </div>
    </Modal>
  )
}
