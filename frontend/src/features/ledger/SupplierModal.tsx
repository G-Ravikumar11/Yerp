import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { ledgerKeys, saveSupplier, type Supplier, type SupplierInput } from '@/api/ledger'
import { useAction } from '@/lib/mutate'

const blank = (): SupplierInput => ({ name: '', contact_person: '', phone: '', email: '', gstin: '', pan: '', address: '', bank_name: '', bank_account: '', bank_ifsc: '', payment_days: 30, supplies: '', msme_type: '', udyam_no: '' })

/** A supplier in the master: who they are, what they supply, how they are paid, and the GSTIN input credit depends on. */
export function SupplierModal({ open, supplier, onClose, presetName }: { open: boolean; supplier: Supplier | null; onClose: () => void; presetName?: string }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title={supplier ? `Edit ${supplier.name}` : 'New supplier'}>
      {open && <Form key={supplier?.id ?? `new-${presetName ?? ''}`} supplier={supplier} presetName={presetName} onClose={onClose} />}
    </Modal>
  )
}

function Form({ supplier, presetName, onClose }: { supplier: Supplier | null; presetName?: string; onClose: () => void }) {
  const [f, setF] = useState<SupplierInput>(() => (supplier ? { ...blank(), ...supplier } : { ...blank(), name: presetName ?? '' }))
  const set = (k: keyof SupplierInput) => (e: React.ChangeEvent<HTMLInputElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const up = (k: keyof SupplierInput) => (e: React.ChangeEvent<HTMLInputElement>) => setF((s) => ({ ...s, [k]: e.target.value.toUpperCase() }))
  const save = useAction(() => saveSupplier(supplier?.id ?? null, f), { invalidate: [ledgerKeys.all, ['suppliers']], success: (r) => `${r.code} ${r.name} saved`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Supplier *" htmlFor="sp-name"><Input id="sp-name" value={f.name} onChange={set('name')} autoFocus /></Field>
        <Field label="Contact person" htmlFor="sp-contact"><Input id="sp-contact" value={f.contact_person} onChange={set('contact_person')} /></Field>
        <Field label="Phone" htmlFor="sp-phone"><Input id="sp-phone" type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Email" htmlFor="sp-email"><Input id="sp-email" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="GSTIN" htmlFor="sp-gstin" hint="Without it, input credit is at risk."><Input id="sp-gstin" className="font-mono uppercase" value={f.gstin} onChange={up('gstin')} /></Field>
        <Field label="PAN" htmlFor="sp-pan"><Input id="sp-pan" className="font-mono uppercase" value={f.pan} onChange={up('pan')} /></Field>
        <Field label="Supplies" htmlFor="sp-supplies" className="sm:col-span-2"><Input id="sp-supplies" value={f.supplies} onChange={set('supplies')} placeholder="Cement, steel, aggregates" /></Field>
        <Field label="Address" htmlFor="sp-address" className="sm:col-span-2"><Input id="sp-address" value={f.address} onChange={set('address')} /></Field>
        <Field label="Bank" htmlFor="sp-bank"><Input id="sp-bank" value={f.bank_name} onChange={set('bank_name')} /></Field>
        <Field label="Account no." htmlFor="sp-acc"><Input id="sp-acc" value={f.bank_account} onChange={set('bank_account')} /></Field>
        <Field label="IFSC" htmlFor="sp-ifsc"><Input id="sp-ifsc" className="font-mono uppercase" value={f.bank_ifsc} onChange={up('bank_ifsc')} /></Field>
        <Field label="Pays in (days)" htmlFor="sp-days"><NumField id="sp-days" value={f.payment_days} onValue={(n) => setF((s) => ({ ...s, payment_days: n }))} /></Field>
        <Field label="MSME (Udyam)" htmlFor="sp-msme" hint={f.msme_type === 'micro' || f.msme_type === 'small' ? 'Paid within 45 days of the bill, whatever is agreed.' : undefined}>
          <Select id="sp-msme" value={f.msme_type} onChange={(e) => setF((s) => ({ ...s, msme_type: e.target.value as SupplierInput['msme_type'] }))}
            options={[{ value: '', label: 'Not registered' }, { value: 'micro', label: 'Micro' }, { value: 'small', label: 'Small' }, { value: 'medium', label: 'Medium' }]} />
        </Field>
        {f.msme_type && <Field label="Udyam number" htmlFor="sp-udyam"><Input id="sp-udyam" className="font-mono uppercase" value={f.udyam_no} onChange={up('udyam_no')} placeholder="UDYAM-TS-02-0012345" /></Field>}
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Save supplier</Button>
      </div>
    </div>
  )
}
