import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { leadKeys, saveLead, type Lead, type LeadInput } from '@/api/leads'
import { useCustomers } from '@/api/customers'
import { useAction } from '@/lib/mutate'

const DATES = ['site_visit_on', 'prebid_on', 'bid_due_on'] as const

/** A tender, as entered and as corrected: who is asking, what it is worth, the dates that matter and the earnest money. */
export function LeadFormModal({ open, lead, sources, modes, onClose, onSaved }: { open: boolean; lead: Lead | null; sources: string[]; modes: string[]; onClose: () => void; onSaved: (l: Lead) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title={lead ? `Edit ${lead.number}` : 'New tender'}>
      {open && <Form lead={lead} sources={sources} modes={modes} onClose={onClose} onSaved={onSaved} />}
    </Modal>
  )
}

function Form({ lead, sources, modes, onClose, onSaved }: { lead: Lead | null; sources: string[]; modes: string[]; onClose: () => void; onSaved: (l: Lead) => void }) {
  const [f, setF] = useState<LeadInput>(() => (lead ? { ...lead } : { title: '', source: sources[0] ?? '' }))
  const customers = useCustomers('')
  const set = (k: keyof LeadInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const text = (k: keyof LeadInput) => String((f[k] as string | number | null | undefined) ?? '')
  const save = useAction(() => saveLead(lead?.id ?? null, f), { invalidate: [leadKeys.all], onSuccess: (r) => { onClose(); onSaved(r.lead) } })

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tender" htmlFor="ld-title" className="sm:col-span-2">
          <Input id="ld-title" value={f.title} onChange={set('title')} placeholder="What is being tendered" autoFocus />
        </Field>
        <Field label="Client" htmlFor="ld-customer">
          <Input id="ld-customer" list="ld-customers" value={text('customer_name')} onChange={set('customer_name')} />
          <datalist id="ld-customers">{(customers.data ?? []).map((c) => <option key={c.id} value={c.name} />)}</datalist>
        </Field>
        <Field label="Source" htmlFor="ld-source">
          <Select id="ld-source" value={text('source')} onChange={set('source')} options={sources.map((s) => ({ value: s, label: s }))} />
        </Field>
        <Field label="Contact person" htmlFor="ld-person">
          <Input id="ld-person" value={text('contact_person')} onChange={set('contact_person')} />
        </Field>
        <Field label="Phone" htmlFor="ld-phone">
          <Input id="ld-phone" type="tel" value={text('phone')} onChange={set('phone')} />
        </Field>
        <Field label="Email" htmlFor="ld-email">
          <Input id="ld-email" type="email" value={text('email')} onChange={set('email')} />
        </Field>
        <Field label="Where" htmlFor="ld-location">
          <Input id="ld-location" value={text('location')} onChange={set('location')} />
        </Field>
        <Field label="Tender reference" htmlFor="ld-ref">
          <Input id="ld-ref" value={text('tender_reference')} onChange={set('tender_reference')} />
        </Field>
        <Field label="Estimated value" htmlFor="ld-value">
          <NumField id="ld-value" value={f.estimated_value} onValue={(n) => setF((s) => ({ ...s, estimated_value: n }))} />
        </Field>
        {DATES.map((k) => (
          <Field key={k} label={{ site_visit_on: 'Site visit', prebid_on: 'Pre-bid meeting', bid_due_on: 'Bid due' }[k]} htmlFor={`ld-${k}`}>
            <Input id={`ld-${k}`} type="date" value={text(k)} onChange={set(k)} />
          </Field>
        ))}
        <Field label="Earnest money (EMD)" htmlFor="ld-emd">
          <NumField id="ld-emd" value={f.emd_amount} onValue={(n) => setF((s) => ({ ...s, emd_amount: n }))} />
        </Field>
        <Field label="EMD mode" htmlFor="ld-emd-mode">
          <Select id="ld-emd-mode" value={text('emd_mode')} onChange={set('emd_mode')} placeholder="None" options={modes.map((s) => ({ value: s, label: s }))} />
        </Field>
        <Field label="EMD reference" htmlFor="ld-emd-ref">
          <Input id="ld-emd-ref" value={text('emd_reference')} onChange={set('emd_reference')} />
        </Field>
        <Field label="EMD paid on" htmlFor="ld-emd-paid">
          <Input id="ld-emd-paid" type="date" value={text('emd_paid_on')} onChange={set('emd_paid_on')} />
        </Field>
        <Field label="Notes" htmlFor="ld-notes" className="sm:col-span-2">
          <Textarea id="ld-notes" rows={2} value={text('notes')} onChange={set('notes')} />
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
        <Button loading={save.isPending} disabled={!f.title.trim()} onClick={() => save.mutate()}>
          Save tender
        </Button>
      </div>
    </div>
  )
}
