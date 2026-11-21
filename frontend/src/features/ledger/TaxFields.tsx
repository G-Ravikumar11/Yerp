import { Check } from 'lucide-react'
import { Button, Field, Input, Select } from '@/components/ui'
import { useMoneyHeads } from '@/api/ledger'
import { GST_RATES, gstSplit } from '@/lib/gstSplit'
import { INDIAN_STATES } from '@/lib/states'
import { formatINR } from '@/lib/utils'
import { accountOk, ifscOk, type BankValue, type TaxValue } from './taxValues'

/* The tax selection and the bank transfer details of an expense: one voucher form, and the recurring payment that raises the same
   expense every month, ask for them the same way. */

/** Tax selection: Taxable or Non taxable; a taxable one is Local or Non local (the two choices hide once one is picked), a non local one
 * names the state, and the tax inside the amount is worked out for it. `amount` is what was paid, tax included. */
export function TaxSelection({ value, onChange, amount, id = 'ev' }: { value: TaxValue; onChange: (v: TaxValue) => void; amount: number; id?: string }) {
  const heads = useMoneyHeads()
  const states = heads.data?.states?.length ? heads.data.states : INDIAN_STATES
  const { tax, supply, state, rate } = value
  const set = (patch: Partial<TaxValue>) => onChange({ ...value, ...patch })
  const stateName = states.find((s) => s.value === state)?.label ?? ''
  const ready = tax === 'taxable' && (supply === 'local' || (supply === 'non_local' && !!state))
  return (
    <div className="grid gap-4">
      <Field label="Tax selection" htmlFor={`${id}-tax`}>
        <Select id={`${id}-tax`} value={tax} onChange={(e) => set({ tax: e.target.value, supply: '', state: '' })} placeholder="Choose taxable or non taxable"
          options={[{ value: 'taxable', label: 'Taxable' }, { value: 'non_taxable', label: 'Non taxable' }]} />
      </Field>
      {tax === 'taxable' && !supply && (
        <div role="group" aria-label="Supply" className="grid grid-cols-2 gap-3">
          {([['local', 'Local'], ['non_local', 'Non local']] as const).map(([v, label]) => (
            <Button key={v} type="button" variant="outline" onClick={() => set({ supply: v })}>{label}</Button>
          ))}
        </div>
      )}
      {tax === 'taxable' && supply && (
        <p className="flex items-center gap-2 text-sm" aria-live="polite">
          <Check className="size-4 text-success" aria-hidden="true" /> Taxable, {supply === 'local' ? 'local' : 'non local'}
          <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => set({ supply: '', state: '' })}>Change</button>
        </p>
      )}
      {tax === 'taxable' && supply === 'non_local' && (
        <Field label="State" htmlFor={`${id}-state`} hint="The state the supply comes from.">
          <Select id={`${id}-state`} value={state} onChange={(e) => set({ state: e.target.value })} placeholder="Choose the state" options={states.map((s) => ({ value: s.value, label: s.label }))} />
        </Field>
      )}
      {ready && (() => {
        const r = Number(rate)
        const g = gstSplit(amount, r, supply as 'local' | 'non_local')
        return (
          <div className="grid gap-3">
            <Field label="GST rate" htmlFor={`${id}-rate`} hint="The amount paid already includes the tax.">
              <Select id={`${id}-rate`} value={rate} onChange={(e) => set({ rate: e.target.value })} options={GST_RATES.map((x) => ({ value: String(x), label: `${x}%` }))} />
            </Field>
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm" aria-label="Tax worked out" role="group">
              {supply === 'non_local'
                ? <p className="font-medium">{stateName}: IGST {r}% = {formatINR(g.igst)}</p>
                : <p className="font-medium">CGST {r / 2}% = {formatINR(g.cgst)} + SGST {r / 2}% = {formatINR(g.sgst)}</p>}
              <p className="mt-0.5 text-[13px] text-muted-foreground">Before tax {formatINR(g.base)}, tax {formatINR(g.tax)}, paid {formatINR(amount)}.</p>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

export function PayeeBankFields({ value, onChange, id = 'ev', legend = 'Bank transfer: where the money went' }: { value: BankValue; onChange: (v: BankValue) => void; id?: string; legend?: string }) {
  const set = (patch: Partial<BankValue>) => onChange({ ...value, ...patch })
  return (
    <fieldset className="grid gap-4 rounded-lg border border-border p-3 sm:grid-cols-3">
      <legend className="px-1 text-[13px] font-medium">{legend}</legend>
      <Field label="Payee bank name" htmlFor={`${id}-pbank`}><Input id={`${id}-pbank`} value={value.bank} onChange={(e) => set({ bank: e.target.value })} placeholder="State Bank of India" /></Field>
      <Field label="Account number" htmlFor={`${id}-pacct`} hint={value.account && !accountOk(value.account) ? '6 to 20 digits' : undefined}><Input id={`${id}-pacct`} inputMode="numeric" value={value.account} onChange={(e) => set({ account: e.target.value })} placeholder="30123456789" /></Field>
      <Field label="IFSC" htmlFor={`${id}-pifsc`} hint={value.ifsc && !ifscOk(value.ifsc) ? 'Like SBIN0001234' : undefined}><Input id={`${id}-pifsc`} value={value.ifsc} onChange={(e) => set({ ifsc: e.target.value.toUpperCase() })} placeholder="SBIN0001234" maxLength={11} /></Field>
    </fieldset>
  )
}
