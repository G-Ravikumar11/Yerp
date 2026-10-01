import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Select, Skeleton, Textarea } from '@/components/ui'
import { PictureField } from '@/components/data/PictureField'
import { useAction } from '@/lib/mutate'
import { saveCompany, saveLogo, settingsKeys, useCompany, useLogo, type BankDetail } from '@/api/settings'
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
    </>
  )
}
