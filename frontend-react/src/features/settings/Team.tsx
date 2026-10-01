import { useState } from 'react'
import { UserPlus } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { inviteMember, removeMember, settingsKeys, updateMember, useTeam, type TeamMember } from '@/api/settings'
import { Section } from './Section'

const ROLES = [{ value: 'admin', label: 'Admin - can change things' }, { value: 'viewer', label: 'Viewer - can only look' }]

function InviteModal({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ email: '', name: '', role: 'admin' })
  const send = useAction(() => inviteMember(f), { invalidate: [settingsKeys.all], success: () => `${f.email} has been emailed a link to set their password.`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Add a colleague" description="They get an email with a link to choose their own password."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={send.isPending} disabled={!f.email.trim()} onClick={() => send.mutate()}>Send invite</Button></>}>
      <div className="grid gap-4">
        <Field label="Name" htmlFor="tm-name"><Input id="tm-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Email" htmlFor="tm-email"><Input id="tm-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Role" htmlFor="tm-role"><Select id="tm-role" options={ROLES} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

type Change = { id: number; body: { role?: string; is_active?: boolean }; msg: string }

/** The owner's own sign-in colleagues - not employees; those are under People. */
export function Team() {
  const q = useTeam()
  const [inviting, setInviting] = useState(false)
  const [removing, setRemoving] = useState<TeamMember | null>(null)
  const change = useAction((v: Change) => updateMember(v.id, v.body), { invalidate: [settingsKeys.all], success: (_r, v) => v.msg })
  const remove = useAction((id: number) => removeMember(id), { invalidate: [settingsKeys.all], onSuccess: () => setRemoving(null) })
  const owner = q.data?.your_role === 'owner'
  const roleOptions = [{ value: 'admin', label: 'Admin' }, { value: 'viewer', label: 'Viewer' }]
  const cols: TableColumn<TeamMember>[] = [
    { id: 'who', header: 'Person', sort: (m) => m.name || m.email, cell: (m) => <div><p className="font-medium">{m.name || m.email}</p>{m.name && <p className="text-xs text-muted-foreground">{m.email}</p>}</div> },
    { id: 'role', header: 'Role', cell: (m) => m.is_account_owner ? <Badge tone="info">Owner</Badge> : owner ? <Select aria-label={`Role of ${m.email}`} className="h-8 w-28" options={roleOptions} value={m.role} onChange={(e) => change.mutate({ id: m.id, body: { role: e.target.value }, msg: 'Role changed' })} /> : <Badge>{m.role}</Badge> },
    { id: 'st', header: 'Status', cell: (m) => !m.is_active ? <Badge tone="danger" dot>Suspended</Badge> : m.accepted ? <Badge tone="success" dot>Active</Badge> : <Badge tone="warning" dot>Invite not used</Badge> },
    { id: 'last', header: 'Last sign-in', hideBelow: 'md', cell: (m) => m.last_login ? formatDate(m.last_login.slice(0, 10)) : 'Never' },
    { id: 'act', header: '', align: 'right', cell: (m) => m.is_account_owner || !owner ? null : (
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="outline" onClick={() => change.mutate({ id: m.id, body: { is_active: !m.is_active }, msg: m.is_active ? 'Access suspended' : 'Access restored' })}>{m.is_active ? 'Suspend' : 'Restore'}</Button>
        <Button size="sm" variant="outline" className="text-danger" onClick={() => setRemoving(m)}>Remove</Button>
      </div>) },
  ]
  return (
    <Section title="Team" description="Colleagues who sign in to the owner's side with their own password." actions={owner && <Button size="sm" onClick={() => setInviting(true)}><UserPlus /> Add a colleague</Button>}>
      {q.isPending ? <Skeleton className="h-24 w-full" /> : <DataTable label="Team" rows={q.data?.members ?? []} columns={cols} rowKey={(m) => m.id} empty="No one yet." />}
      {inviting && <InviteModal onClose={() => setInviting(false)} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.name || removing?.email}?`} description="They will not be able to sign in. Anything they did stays on record." confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing.id) }} />
    </Section>
  )
}
