import { useEffect, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, ConfirmDialog, Field, Input, Modal, Textarea } from '@/components/ui'
import { contactKeys, createContact, deleteContact, updateContact, useContacts, type Contact, type ContactInput } from '@/api/contacts'
import { useAction } from '@/lib/mutate'

const blank: ContactInput = { name: '', email: '', phone_number: '', contact_person: '', gstin: '', address: '', city: '', state: '', pincode: '' }

function ContactModal({ contact, onClose }: { contact: Contact | 'new'; onClose: () => void }) {
  const [f, setF] = useState<ContactInput>(blank)
  useEffect(() => setF(contact === 'new' ? blank : { ...blank, ...contact }), [contact])
  const set = (k: keyof ContactInput) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))
  const save = useAction(() => (contact === 'new' ? createContact({ ...f, gstin: f.gstin.toUpperCase() }) : updateContact(contact.id, { ...f, gstin: f.gstin.toUpperCase() })), {
    invalidate: [contactKeys.all, ['customers']],
    success: contact === 'new' ? 'Contact created' : 'Contact updated',
    onSuccess: onClose,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={contact === 'new' ? 'New contact' : 'Edit contact'} description="For a client or supplier: what goes on the bill and on the e-invoice."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Save contact</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="ct-name" className="sm:col-span-2"><Input id="ct-name" value={f.name} onChange={set('name')} /></Field>
        <Field label="Email" htmlFor="ct-email"><Input id="ct-email" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Phone" htmlFor="ct-phone"><Input id="ct-phone" value={f.phone_number} onChange={set('phone_number')} /></Field>
        <Field label="Person to deal with" htmlFor="ct-person"><Input id="ct-person" value={f.contact_person} onChange={set('contact_person')} /></Field>
        <Field label="GSTIN" htmlFor="ct-gstin"><Input id="ct-gstin" maxLength={15} value={f.gstin} onChange={set('gstin')} /></Field>
        <Field label="Billing address" htmlFor="ct-addr" className="sm:col-span-2"><Textarea id="ct-addr" rows={2} value={f.address} onChange={set('address')} /></Field>
        <Field label="City" htmlFor="ct-city"><Input id="ct-city" value={f.city} onChange={set('city')} /></Field>
        <Field label="State" htmlFor="ct-state" hint="From the GSTIN if blank."><Input id="ct-state" value={f.state} onChange={set('state')} /></Field>
        <Field label="PIN" htmlFor="ct-pin"><Input id="ct-pin" maxLength={6} inputMode="numeric" value={f.pincode} onChange={set('pincode')} /></Field>
      </div>
    </Modal>
  )
}

/** Everyone the business bills or buys from, as one plain list. */
export default function ContactsPage() {
  const q = useContacts()
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<Contact | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Contact | null>(null)
  const remove = useAction((id: number) => deleteContact(id), { invalidate: [contactKeys.all, ['customers']], success: 'Contact deleted', onSuccess: () => setDeleting(null) })
  const s = search.trim().toLowerCase()
  const rows = (q.data ?? []).filter((c) => !s || [c.name, c.email, c.gstin, c.phone_number].some((v) => (v || '').toLowerCase().includes(s)))
  const columns: TableColumn<Contact>[] = [
    { id: 'name', header: 'Name', sort: (c) => c.name, cell: (c) => <div><span className="font-medium">{c.name || "-"}</span>{(c.city || c.state) && <p className="text-xs text-muted-foreground">{[c.city, c.state].filter(Boolean).join(', ')}</p>}</div> },
    { id: 'gstin', header: 'GSTIN', cell: (c) => <span className="font-mono text-[13px]">{c.gstin || '-'}</span> },
    { id: 'email', header: 'Email', hideBelow: 'md', cell: (c) => c.email || '-' },
    { id: 'phone', header: 'Phone', hideBelow: 'md', cell: (c) => c.phone_number || '-' },
    { id: 'act', header: '', align: 'right', cell: (c) => <div className="flex justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => setEditing(c)}>Edit</Button><Button size="sm" variant="outline" className="text-danger" onClick={() => setDeleting(c)}>Delete</Button></div> },
  ]
  return (
    <>
      <PageHeader eyebrow="Clients" title="Contacts" description="The people and companies you bill or buy from." actions={<Button onClick={() => setEditing('new')}><Plus /> New contact</Button>} />
      <div className="mb-4 max-w-sm"><Input aria-label="Search contacts" placeholder="Search contacts" leading={<Search />} value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <DataTable label="Contacts" rows={rows} columns={columns} rowKey={(c) => c.id} loading={q.isPending} empty="No contacts found." />
      {editing && <ContactModal contact={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} title={`Delete ${deleting?.name}?`} description="It is taken off the list. Documents already issued keep what was printed on them." confirmLabel="Delete" tone="danger" loading={remove.isPending} onConfirm={() => { if (deleting) remove.mutate(deleting.id) }} />
    </>
  )
}
