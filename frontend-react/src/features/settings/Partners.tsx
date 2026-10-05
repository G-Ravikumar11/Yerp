import { useState } from 'react'
import { UserPlus } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { invitePartner, reinvitePartner, settingsKeys, switchPartner, usePortalAccess, type InviteResult, type PortalUser } from '@/api/settings'
import { toast } from '@/stores/toast'
import { Section } from './Section'

function InviteModal({ onClose, onDone }: { onClose: () => void; onDone: (r: InviteResult) => void }) {
  const q = usePortalAccess()
  const [type, setType] = useState('contractor')
  const [party, setParty] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const list = (type === 'contractor' ? q.data?.contractors : q.data?.suppliers) ?? []
  const pick = (id: string) => {
    setParty(id)
    const p = list.find((x) => String(x.id) === id)
    if (p) { setName(p.contact || p.name); setEmail(p.email || '') }
  }
  const send = useAction(() => invitePartner({ party_type: type, party_id: Number(party), name, email }), { invalidate: [settingsKeys.all], onSuccess: (r) => { onDone(r); onClose() } })
  const kinds = [{ value: 'contractor', label: 'Subcontractor' }, { value: 'supplier', label: 'Supplier' }]
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Give a partner a login" description="One person at a contractor or supplier. They see only their own orders, bills and statements."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={send.isPending} disabled={!party || !email.trim()} onClick={() => send.mutate()}>Send invite</Button></>}>
      <div className="grid gap-4">
        <Field label="Kind" htmlFor="pa-type"><Select id="pa-type" options={kinds} value={type} onChange={(e) => { setType(e.target.value); setParty('') }} /></Field>
        <Field label="Who" htmlFor="pa-party"><Select id="pa-party" placeholder="Choose" options={list.map((p) => ({ value: p.id, label: p.name }))} value={party} onChange={(e) => pick(e.target.value)} /></Field>
        <Field label="Their name" htmlFor="pa-name"><Input id="pa-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Email they sign in with" htmlFor="pa-email"><Input id="pa-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}

/** Logins for the gangs and suppliers: invite, send a fresh link, switch off. */
export function Partners() {
  const q = usePortalAccess()
  const [inviting, setInviting] = useState(false)
  const [link, setLink] = useState<InviteResult | null>(null)
  const refresh = [settingsKeys.all]
  const reinvite = useAction((id: number) => reinvitePartner(id), { invalidate: refresh, onSuccess: (r) => setLink(r) })
  const sw = useAction((v: { id: number; action: 'enable' | 'disable' }) => switchPartner(v.id, v.action), { invalidate: refresh })
  const cols: TableColumn<PortalUser>[] = [
    { id: 'who', header: 'Login', cell: (u) => <div><p className="font-medium">{u.name || u.email}</p><p className="text-xs text-muted-foreground">{u.email}</p></div> },
    { id: 'party', header: 'For', cell: (u) => <span>{u.party} <span className="text-xs text-muted-foreground">({u.party_type === 'contractor' ? 'subcontractor' : 'supplier'})</span></span> },
    { id: 'st', header: 'Status', cell: (u) => !u.is_active ? <Badge tone="danger" dot>Off</Badge> : u.has_password ? <Badge tone="success" dot>Active</Badge> : u.invite_open ? <Badge tone="warning" dot>Invited</Badge> : <Badge tone="danger" dot>Link expired</Badge> },
    { id: 'last', header: 'Last sign-in', hideBelow: 'md', cell: (u) => u.last_login ? formatDate(u.last_login.slice(0, 10)) : 'Never' },
    { id: 'act', header: '', align: 'right', cell: (u) => (
      <div className="flex justify-end gap-1.5">
        {u.is_active && <Button size="sm" variant="outline" loading={reinvite.isPending} onClick={() => reinvite.mutate(u.id)}>New link</Button>}
        <Button size="sm" variant="outline" onClick={() => sw.mutate({ id: u.id, action: u.is_active ? 'disable' : 'enable' })}>{u.is_active ? 'Turn off' : 'Turn on'}</Button>
      </div>) },
  ]
  const copy = () => { if (link) { void navigator.clipboard?.writeText(link.invite_url); toast.success('Link copied') } }
  return (
    <Section title="Partner logins" description="Subcontractors and suppliers who sign in to their own portal." actions={<Button size="sm" variant="outline" onClick={() => setInviting(true)}><UserPlus /> Invite a partner</Button>}>
      {q.isPending ? <Skeleton className="h-24 w-full" /> : <DataTable label="Partner logins" rows={q.data?.users ?? []} columns={cols} rowKey={(u) => u.id} empty="No partner has a login yet." />}
      {link && (
        <div role="status" className="mt-3 rounded-lg border border-border bg-muted p-3 text-sm">
          <p>{link.emailed ? 'The link was emailed. ' : 'Email is not set up, so send them this link yourself. '}It works for a limited time.</p>
          <div className="mt-2 flex gap-2"><Input readOnly aria-label="Invite link" value={link.invite_url} onFocus={(e) => e.currentTarget.select()} /><Button size="sm" variant="outline" onClick={copy}>Copy</Button></div>
        </div>
      )}
      {inviting && <InviteModal onClose={() => setInviting(false)} onDone={setLink} />}
    </Section>
  )
}
