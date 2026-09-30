import { useState } from 'react'
import { Button, Field, Input, Modal, Textarea } from '@/components/ui'
import { createCustomer, customerKeys, updateCustomer, type Customer, type CustomerInput } from '@/api/customers'
import { useAction } from '@/lib/mutate'

const blank = (): CustomerInput => ({ name: '', contact_person: '', email: '', phone_number: '', gstin: '', pan: '', address: '', city: '', state: '', pincode: '', notes: '' })

/** The party a project belongs to, with the detail its paperwork needs: their PAN, GSTIN and address print on every bill. */
export function CustomerFormModal({ open, customer, onClose, presetName }: { open: boolean; customer: Customer | null; onClose: () => void; presetName?: string }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title={customer ? `Edit ${customer.name}` : 'Add new customer'}>
      {open && <Form key={customer?.id ?? 'new'} customer={customer} presetName={presetName} onClose={onClose} />}
    </Modal>
  )
}

function Form({ customer, presetName, onClose }: { customer: Customer | null; presetName?: string; onClose: () => void }) {
  const [f, setF] = useState<CustomerInput>(() => (customer ? { ...blank(), ...customer } : { ...blank(), name: presetName ?? '' }))
  const set = (k: keyof CustomerInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const upper = (k: keyof CustomerInput) => (e: React.ChangeEvent<HTMLInputElement>) => setF((s) => ({ ...s, [k]: e.target.value.toUpperCase() }))
  const save = useAction(() => {
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v])) as CustomerInput
    return customer ? updateCustomer(customer.id, body) : createCustomer(body)
  }, { invalidate: [customerKeys.all, ['jobs']], onSuccess: onClose })

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Customer name *" htmlFor="cu-name">
          <Input id="cu-name" value={f.name} onChange={set('name')} placeholder="L&T Construction" autoFocus />
        </Field>
        <Field label="Contact person" htmlFor="cu-person">
          <Input id="cu-person" value={f.contact_person} onChange={set('contact_person')} placeholder="Who signs" />
        </Field>
        <Field label="Email" htmlFor="cu-email">
          <Input id="cu-email" type="email" value={f.email} onChange={set('email')} placeholder="accounts@example.in" />
        </Field>
        <Field label="Phone" htmlFor="cu-phone">
          <Input id="cu-phone" type="tel" value={f.phone_number} onChange={set('phone_number')} placeholder="98765 00000" />
        </Field>
        <Field label="GSTIN" htmlFor="cu-gstin">
          <Input id="cu-gstin" value={f.gstin} onChange={upper('gstin')} placeholder="36AAACL0140P1Z8" className="font-mono uppercase" />
        </Field>
        <Field label="PAN" htmlFor="cu-pan" hint="Read from the GSTIN if left blank.">
          <Input id="cu-pan" value={f.pan} onChange={upper('pan')} placeholder="AAACL0140P" className="font-mono uppercase" />
        </Field>
        <Field label="Address" htmlFor="cu-address" className="sm:col-span-2">
          <Input id="cu-address" value={f.address} onChange={set('address')} placeholder="Site or registered address" />
        </Field>
        <Field label="City" htmlFor="cu-city">
          <Input id="cu-city" value={f.city} onChange={set('city')} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="State" htmlFor="cu-state">
            <Input id="cu-state" value={f.state} onChange={set('state')} />
          </Field>
          <Field label="Pincode" htmlFor="cu-pin">
            <Input id="cu-pin" value={f.pincode} onChange={set('pincode')} />
          </Field>
        </div>
        <Field label="Notes" htmlFor="cu-notes" className="sm:col-span-2">
          <Textarea id="cu-notes" rows={2} value={f.notes} onChange={set('notes')} />
        </Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && (
          <p role="alert" className="mr-auto text-[13px] text-danger">
            {save.error.message}
          </p>
        )}
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>
          Save customer
        </Button>
      </div>
    </div>
  )
}
