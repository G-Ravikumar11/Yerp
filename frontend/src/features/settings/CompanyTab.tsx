import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { Check, Circle } from 'lucide-react'
import { Button, Field, Input, NumField, Select, Skeleton, Textarea } from '@/components/ui'
import { MANDATORY, useIdentity } from '@/api/identity'
import { PictureField } from '@/components/data/PictureField'
import { useAction } from '@/lib/mutate'
import { saveCompany, saveLogo, settingsKeys, useCompany, useLogo, type BankDetail } from '@/api/settings'
import { storeKeys } from '@/api/store'
import { paymentKeys, savePaymentRules, usePaymentRules } from '@/api/payments'
import { Section } from './Section'
import { TaxRates } from './TaxRates'

const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD'].map((c) => ({ value: c, label: c }))
const blankBank = (): BankDetail => ({ bank_name: '', account_name: '', account_number: '', sort_code: '' })

function parseBanks(raw: string | undefined): BankDetail[] {
  try {
    const list = JSON.parse(raw || '[]')
    return Array.isArray(list) && list.length ? list.map((b) => ({ ...blankBank(), ...b })) : [blankBank()]
  } catch {
    return [blankBank()]
  }
}

/** What every document carries, and which of it is still to be given. One list for the whole app. */
function Mandatory() {
  const { data } = useIdentity()
  if (!data) return null
  const lacking = new Set(data.missing.map((m) => m.toLowerCase()))
  const missing = (label: string) => lacking.has(label.toLowerCase()) || (label === 'Company name' && lacking.has('company name'))
  return (
    <Section title="On every document" description="These are printed at the head of every work order, bill, purchase order, statement, form and Excel export - and shown across the app. All of them are needed.">
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Mandatory company details">
        {MANDATORY.map(({ key, label }) => {
          const lack = missing(label)
          return (
            <li key={key} className="flex items-center gap-2 text-sm">
              {lack ? <Circle className="size-4 text-warning" aria-hidden /> : <Check className="size-4 text-success" aria-hidden />}
              <span className={lack ? 'font-medium' : 'text-muted-foreground'}>{label}</span>
              {lack && <span className="text-xs text-warning">missing</span>}
              {!lack && key !== 'logo_url' && <span className="truncate text-xs text-muted-foreground">{String(data[key]).split(String.fromCharCode(10))[0].trim()}</span>}
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

/** The company as it prints on documents: name, GSTIN, address, logo and the bank accounts. */
export default function CompanyTab() {
  const q = useCompany()
  const logo = useLogo()
  const [f, setF] = useState({ name: '', email: '', phone: '', address: '', gstin: '', website: '', currency: 'INR' })
  const [banks, setBanks] = useState<BankDetail[]>([blankBank()])
  const [pic, setPic] = useState('')
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))

  useEffect(() => {
    const d = q.data
    if (!d) return
    setF({ name: d.company_name || '', email: d.company_email || d.email || '', phone: d.company_phone || d.phone_number || '', address: d.company_address || '', gstin: d.company_abn || '', website: d.company_website || '', currency: d.currency || 'INR' })
    setBanks(parseBanks(d.bank_details))
  }, [q.data])
  useEffect(() => setPic(logo.data?.logo_url ?? ''), [logo.data])

  const save = useAction(
    () =>
      saveCompany({
        company_name: f.name,
        company_email: f.email,
        email: f.email,
        company_phone: f.phone,
        phone_number: f.phone,
        company_address: f.address,
        company_abn: f.gstin,
        company_website: f.website,
        currency: f.currency,
        bank_details: JSON.stringify(banks.filter((b) => b.bank_name || b.account_number)),
      }),
    { invalidate: [settingsKeys.all, ['session']], success: 'Company details saved.' },
  )
  const saveLogoAction = useAction(() => saveLogo(pic), { invalidate: [settingsKeys.all], success: 'Logo saved.' })
  const editBank = (i: number, k: keyof BankDetail, v: string) => setBanks((l) => l.map((b, j) => (j === i ? { ...b, [k]: v } : b)))

  if (q.isPending) return <Skeleton className="h-96 w-full" />
  return (
    <>
      <Mandatory />
      <Section title="Company details" description="Printed on every work order, bill, purchase order and statement.">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          <Field label="Company name" htmlFor="co-name"><Input id="co-name" value={f.name} onChange={set('name')} /></Field>
          <Field label="GSTIN" htmlFor="co-gstin" hint="Fifteen characters. It also sets the company's state."><Input id="co-gstin" value={f.gstin} onChange={set('gstin')} /></Field>
          <Field label="Email" htmlFor="co-email"><Input id="co-email" type="email" value={f.email} onChange={set('email')} /></Field>
          <Field label="Phone" htmlFor="co-phone"><Input id="co-phone" value={f.phone} onChange={set('phone')} /></Field>
          <Field label="Website" htmlFor="co-web"><Input id="co-web" value={f.website} onChange={set('website')} /></Field>
          <Field label="Currency" htmlFor="co-cur"><Select id="co-cur" options={CURRENCIES} value={f.currency} onChange={set('currency')} /></Field>
          <Field label="Address" htmlFor="co-addr" className="sm:col-span-2"><Textarea id="co-addr" rows={3} value={f.address} onChange={set('address')} /></Field>
          <div className="sm:col-span-2">
            <p className="mb-2 text-[13px] font-medium">Bank accounts</p>
            <div className="flex flex-col gap-3">
              {banks.map((b, i) => (
                <div key={i} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_8rem_auto]">
                  <Input aria-label={`Bank ${i + 1} name`} placeholder="Bank" value={b.bank_name} onChange={(e) => editBank(i, 'bank_name', e.target.value)} />
                  <Input aria-label={`Bank ${i + 1} account name`} placeholder="Account name" value={b.account_name} onChange={(e) => editBank(i, 'account_name', e.target.value)} />
                  <Input aria-label={`Bank ${i + 1} account number`} placeholder="Account number" value={b.account_number} onChange={(e) => editBank(i, 'account_number', e.target.value)} />
                  <Input aria-label={`Bank ${i + 1} IFSC`} placeholder="IFSC" value={b.sort_code} onChange={(e) => editBank(i, 'sort_code', e.target.value)} />
                  <Button type="button" variant="ghost" size="icon" aria-label={`Remove bank ${i + 1}`} onClick={() => setBanks((l) => (l.length > 1 ? l.filter((_, j) => j !== i) : [blankBank()]))}><Trash2 className="size-4" /></Button>
                </div>
              ))}
            </div>
            <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => setBanks((l) => [...l, blankBank()])}><Plus /> Add a bank account</Button>
          </div>
          <div className="sm:col-span-2"><Button type="submit" loading={save.isPending}>Save company details</Button></div>
        </form>
      </Section>
      <Section title="Company logo" description="The logo on invoices, statements and documents that have no letterhead of their own.">
        <PictureField label="Logo" value={pic} onChange={setPic} hint="PNG or JPEG. It is shrunk to fit." />
        <Button className="mt-3" loading={saveLogoAction.isPending} onClick={() => saveLogoAction.mutate()}>Save logo</Button>
      </Section>
      <TaxRates />
      <StoreScanning />
      <PaymentApproval />
    </>
  )
}

/** QR codes and barcodes in the Store: off unless a store wants them, so the screens stay as simple as they were. */
function StoreScanning() {
  const q = useCompany()
  const qc = useQueryClient()
  const on = ['true', '1', 'yes', 'on'].includes(String(q.data?.store_scanning ?? '').toLowerCase())
  const save = useAction((v: boolean) => saveCompany({ store_scanning: v ? 'true' : 'false' }), {
    invalidate: [[...settingsKeys.all]],
    success: (_r, v) => (v ? 'Scanning is on in the Store' : 'Scanning is off in the Store'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...storeKeys.meta] }),
  })
  return (
    <Section title="Store: QR codes and barcodes" description="For a central store with racks of small look-alike items, packaged goods with the maker's barcode, or a gate that checks gate passes on a phone. Loose material - cement, sand, aggregate, steel - needs none of it.">
      <label className="flex items-start gap-3 text-sm">
        <input type="checkbox" className="mt-0.5" checked={on} disabled={q.isPending || save.isPending} onChange={(e) => save.mutate(e.target.checked)} />
        <span>
          <span className="font-medium">Use scanning in the Store</span>
          <span className="block text-muted-foreground">Shows the Scan button in the Store Hub and on the item and store boxes, the maker's barcode in item settings, printing of bin and rack labels, and a QR on printed gate passes. A handheld barcode scanner works in the item box either way.</span>
        </span>
      </label>
    </Section>
  )
}

/** Payments approved before they are made: the accounts head checks each, the MD releases the large ones. */
function PaymentApproval() {
  const q = usePaymentRules()
  const [f, setF] = useState<{ on: boolean; free_below: number; md_above: number } | null>(null)
  const shown = f ?? (q.data ? { on: q.data.on, free_below: q.data.free_below, md_above: q.data.md_above } : null)
  const save = useAction(() => savePaymentRules(shown!), { invalidate: [[...paymentKeys.all]], onSuccess: () => setF(null) })
  if (!shown) return null
  const set = (patch: Partial<typeof shown>) => setF({ ...shown, ...patch })
  return (
    <Section title="Payment approval" description="Accounts send a payment for approval; the accounts head checks it, and over the MD's limit the MD releases it too; only then is it paid. Give 'Check payments' and 'Release payments over the MD's limit' to the right people under People, Employees. You pay without asking.">
      <label className="mb-4 flex items-start gap-3 text-sm">
        <input type="checkbox" className="mt-0.5" checked={shown.on} onChange={(e) => set({ on: e.target.checked })} />
        <span><span className="font-medium">Approve payments before they are made</span>
          <span className="block text-muted-foreground">Supplier and contractor bills, advances and expense vouchers paid out. Money received never waits.</span></span>
      </label>
      <div className="grid max-w-xl gap-4 sm:grid-cols-2">
        <Field label="No approval up to (Rs)" htmlFor="pa-free" hint="Small cash payments go straight through"><NumField id="pa-free" value={shown.free_below} onValue={(n) => set({ free_below: n })} disabled={!shown.on} /></Field>
        <Field label="The MD releases over (Rs)" htmlFor="pa-md" hint="Above this, two signatures"><NumField id="pa-md" value={shown.md_above} onValue={(n) => set({ md_above: n })} disabled={!shown.on} /></Field>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button size="sm" loading={save.isPending} disabled={!f} onClick={() => save.mutate()}>Save payment approval</Button>
        {save.error && <p role="alert" className="text-[13px] text-danger">{save.error.message}</p>}
      </div>
    </Section>
  )
}
