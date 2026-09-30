import { useState } from 'react'
import { FileCheck2, Paperclip } from 'lucide-react'
import { Button, Field, Input, Modal, Textarea } from '@/components/ui'
import { createVendor, updateVendor, vendorKeys, VENDOR_DOCS, type Vendor, type VendorInput } from '@/api/vendors'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'

const MAX_BYTES = 5 * 1024 * 1024

const blank = (): Partial<Vendor> => ({
  company_name: '',
  vendor_code: '',
  registered_project: '',
  joining_date: '',
  address: '',
  pin_code: '',
  city: '',
  state: '',
  nature_of_work: '',
  phone_number: '',
  email: '',
  contact_person: '',
  entity_type: '',
  pan: '',
  gst_number: '',
  aadhaar: '',
  bank_name: '',
  bank_branch: '',
  bank_account: '',
  bank_ifsc: '',
  documents: [],
  declaration_signed: false,
})

const readFile = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result))
    r.onerror = () => reject(new Error('Could not read that file'))
    r.readAsDataURL(file)
  })

/** The Sub Contractor Registration Form, box for box - with each required document attached as a PDF or a picture. */
export function VendorFormModal({ vendor, open, onOpenChange }: { vendor: Vendor | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title={vendor ? `Registration form - ${vendor.vendor_code} ${vendor.company_name}` : 'Sub Contractor Registration Form'} description="Registered by staff, the form waits in Approvals until somebody who approves work orders signs it off.">
      {open && <Form key={vendor?.id ?? 'new'} vendor={vendor} onClose={() => onOpenChange(false)} />}
    </Modal>
  )
}

function Section({ children }: { children: string }) {
  return <div className="sm:col-span-2 rounded-lg bg-muted px-3 py-1.5 text-[13px] font-semibold">{children}</div>
}

function Form({ vendor, onClose }: { vendor: Vendor | null; onClose: () => void }) {
  const [f, setF] = useState<Partial<Vendor>>(() => (vendor ? { ...vendor } : blank()))
  const [files, setFiles] = useState<Record<string, { name: string; data: string }>>({})
  const set = (k: keyof Vendor) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const upper = (k: keyof Vendor) => (e: React.ChangeEvent<HTMLInputElement>) => setF((s) => ({ ...s, [k]: e.target.value.toUpperCase() }))

  const save = useAction(
    () => {
      const body: VendorInput = {
        company_name: f.company_name ?? '',
        vendor_code: f.vendor_code,
        registered_project: f.registered_project,
        joining_date: f.joining_date,
        address: f.address,
        pin_code: f.pin_code,
        city: f.city,
        state: f.state,
        nature_of_work: f.nature_of_work,
        phone_number: f.phone_number,
        email: f.email,
        contact_person: f.contact_person,
        entity_type: f.entity_type,
        pan: f.pan,
        gst_number: f.gst_number,
        aadhaar: f.aadhaar,
        bank_name: f.bank_name,
        bank_branch: f.bank_branch,
        bank_account: f.bank_account,
        bank_ifsc: f.bank_ifsc,
        documents: f.documents,
        declaration_signed: f.declaration_signed,
        ...(Object.keys(files).length ? { document_files: files } : {}),
      }
      return vendor ? updateVendor(vendor.id, body) : createVendor(body)
    },
    { invalidate: [vendorKeys.all, ['approvals']], onSuccess: onClose },
  )

  const toggleDoc = (key: string, on: boolean) => setF((s) => ({ ...s, documents: on ? [...new Set([...(s.documents ?? []), key])] : (s.documents ?? []).filter((d) => d !== key) }))

  const attach = async (key: string, file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_BYTES) return toast.error('That file is too large - keep it under 5 MB.')
    try {
      const data = await readFile(file)
      setFiles((s) => ({ ...s, [key]: { name: file.name, data } }))
      toggleDoc(key, true)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!f.company_name?.trim()) return toast.error('The form needs the name of the sub contractor.')
        save.mutate()
      }}
      className="grid gap-x-4 gap-y-4 sm:grid-cols-2"
    >
      <Field label="Project" htmlFor="v-project" className="sm:col-span-2">
        <Input id="v-project" value={f.registered_project ?? ''} onChange={set('registered_project')} placeholder="The project they were taken on for" />
      </Field>
      <Field label="Vendor code" htmlFor="v-code" hint="Next in the series if left blank.">
        <Input id="v-code" value={f.vendor_code ?? ''} onChange={upper('vendor_code')} className="font-mono uppercase" />
      </Field>
      <Field label="Date of joining" htmlFor="v-join">
        <Input id="v-join" type="date" value={f.joining_date ?? ''} onChange={set('joining_date')} />
      </Field>

      <Section>1. Subcontractor personal details</Section>
      <Field label="Name of the sub contractor *" htmlFor="v-name" className="sm:col-span-2">
        <Input id="v-name" value={f.company_name ?? ''} onChange={set('company_name')} placeholder="M/s ..." autoFocus />
      </Field>
      <Field label="Residential address" htmlFor="v-address" className="sm:col-span-2">
        <Textarea id="v-address" value={f.address ?? ''} onChange={set('address')} rows={2} />
      </Field>
      <Field label="Pin code" htmlFor="v-pin">
        <Input id="v-pin" value={f.pin_code ?? ''} onChange={set('pin_code')} inputMode="numeric" />
      </Field>
      <Field label="City" htmlFor="v-city">
        <Input id="v-city" value={f.city ?? ''} onChange={set('city')} />
      </Field>
      <Field label="State" htmlFor="v-state">
        <Input id="v-state" value={f.state ?? ''} onChange={set('state')} />
      </Field>
      <Field label="Nature of work" htmlFor="v-nature">
        <Input id="v-nature" value={f.nature_of_work ?? ''} onChange={set('nature_of_work')} placeholder="Putty and painting works" />
      </Field>
      <Field label="Tel no." htmlFor="v-phone">
        <Input id="v-phone" type="tel" value={f.phone_number ?? ''} onChange={set('phone_number')} />
      </Field>
      <Field label="E-mail" htmlFor="v-email">
        <Input id="v-email" type="email" value={f.email ?? ''} onChange={set('email')} />
      </Field>
      <Field label="Name of contact person" htmlFor="v-contact">
        <Input id="v-contact" value={f.contact_person ?? ''} onChange={set('contact_person')} />
      </Field>
      <Field label="Type of entity" htmlFor="v-entity">
        <Input id="v-entity" value={f.entity_type ?? ''} onChange={set('entity_type')} placeholder="Individual, proprietorship, firm..." />
      </Field>
      <Field label="PAN" htmlFor="v-pan">
        <Input id="v-pan" value={f.pan ?? ''} onChange={upper('pan')} className="font-mono uppercase" placeholder="AFVPF9080M" />
      </Field>
      <Field label="GST Reg No" htmlFor="v-gst">
        <Input id="v-gst" value={f.gst_number ?? ''} onChange={upper('gst_number')} className="font-mono uppercase" placeholder="37AAAPR1234C1Z5" />
      </Field>
      <Field label="Aadhaar" htmlFor="v-aadhaar">
        <Input id="v-aadhaar" value={f.aadhaar ?? ''} onChange={set('aadhaar')} inputMode="numeric" placeholder="Twelve digits" />
      </Field>

      <Section>2. Bank details</Section>
      <Field label="Bank name" htmlFor="v-bank">
        <Input id="v-bank" value={f.bank_name ?? ''} onChange={set('bank_name')} />
      </Field>
      <Field label="Branch" htmlFor="v-branch">
        <Input id="v-branch" value={f.bank_branch ?? ''} onChange={set('bank_branch')} />
      </Field>
      <Field label="Account no" htmlFor="v-account">
        <Input id="v-account" value={f.bank_account ?? ''} onChange={set('bank_account')} className="font-mono" inputMode="numeric" />
      </Field>
      <Field label="IFSC code" htmlFor="v-ifsc">
        <Input id="v-ifsc" value={f.bank_ifsc ?? ''} onChange={upper('bank_ifsc')} className="font-mono uppercase" />
      </Field>

      <Section>3. Documents required</Section>
      <div className="grid gap-x-6 gap-y-3 sm:col-span-2 sm:grid-cols-2">
        {VENDOR_DOCS.map((d) => {
          const chosen = files[d.key]
          const onFile = vendor?.document_files?.[d.key]
          return (
            <div key={d.key} className="text-[13.5px]">
              <label className="flex items-center gap-2.5 font-medium">
                <input type="checkbox" checked={(f.documents ?? []).includes(d.key)} onChange={(e) => toggleDoc(d.key, e.target.checked)} className="size-4 accent-[var(--primary)]" />
                {d.label}
              </label>
              <div className="mt-1.5 flex items-center gap-2 pl-6">
                <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-input px-2.5 py-1 text-xs font-medium transition-colors hover:bg-accent">
                  <Paperclip className="size-3.5" /> {chosen || onFile ? 'Replace' : 'Attach'}
                  <input type="file" accept=".pdf,image/*" className="sr-only" aria-label={`Attach ${d.label}`} onChange={(e) => void attach(d.key, e.target.files?.[0])} />
                </label>
                {chosen ? (
                  <span className="flex min-w-0 items-center gap-1 text-xs text-success">
                    <FileCheck2 className="size-3.5 shrink-0" /> <span className="truncate">{chosen.name}</span>
                  </span>
                ) : onFile && vendor ? (
                  <a className="min-w-0 truncate text-xs text-primary underline underline-offset-4" href={`/api/wo/contractors/${vendor.id}/documents/${d.key}`} target="_blank" rel="noopener">
                    {onFile}
                  </a>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>

      <Section>Declaration</Section>
      <label className="flex items-start gap-2.5 text-[13px] sm:col-span-2">
        <input type="checkbox" checked={!!f.declaration_signed} onChange={(e) => setF((s) => ({ ...s, declaration_signed: e.target.checked }))} className="mt-0.5 size-4 accent-[var(--primary)]" />
        The sub contractor has signed the declaration: the information is correct, they agree to the Contract for Services and the Health &amp; Safety guidance, will report any change of bank, address or contact, and have given the documents and photo ID.
      </label>

      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          Save the form
        </Button>
      </div>
    </form>
  )
}
