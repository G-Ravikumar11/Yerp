import { Field, Input, Select } from '@/components/ui'

/** The payroll part of an employee form: where the pay goes, which statutory deductions apply, and the probation and contract end dates. */
export interface PayrollValues {
  bank_name?: string
  bank_account?: string
  bank_ifsc?: string
  pf_enabled?: boolean
  esi_enabled?: boolean
  pt_enabled?: boolean
  pt_state?: string
  probation_end_date?: string
  contract_end_date?: string
}

const STATES = [{ value: 'TS', label: 'Telangana (TS)' }, { value: 'AP', label: 'Andhra Pradesh (AP)' }]

export function PayrollFields({ id, value, onChange }: { id: string; value: PayrollValues; onChange: (patch: PayrollValues) => void }) {
  const on = (k: 'pf_enabled' | 'esi_enabled' | 'pt_enabled') => value[k] !== false
  const check = (k: 'pf_enabled' | 'esi_enabled' | 'pt_enabled', label: string, hint: string) => (
    <label className="flex items-start gap-2 text-[13px]">
      <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={on(k)} onChange={(e) => onChange({ [k]: e.target.checked })} />
      <span>{label}<span className="block text-xs text-muted-foreground">{hint}</span></span>
    </label>
  )
  return (
    <>
      <div className="col-span-full mt-1 border-t border-border pt-4"><h4 className="text-sm font-semibold">Bank and statutory deductions</h4></div>
      <Field label="Bank name" htmlFor={`${id}-bank`}><Input id={`${id}-bank`} value={value.bank_name ?? ''} onChange={(e) => onChange({ bank_name: e.target.value })} /></Field>
      <Field label="Bank account number" htmlFor={`${id}-acct`}><Input id={`${id}-acct`} inputMode="numeric" autoComplete="off" value={value.bank_account ?? ''} onChange={(e) => onChange({ bank_account: e.target.value })} /></Field>
      <Field label="IFSC" htmlFor={`${id}-ifsc`} hint="11 characters, like HDFC0001234."><Input id={`${id}-ifsc`} maxLength={11} autoComplete="off" value={value.bank_ifsc ?? ''} onChange={(e) => onChange({ bank_ifsc: e.target.value.toUpperCase().replace(/\s/g, '') })} /></Field>
      <div className="col-span-full grid gap-3 sm:grid-cols-3">
        {check('pf_enabled', 'Provident Fund', '12% of the basic pay, up to 15,000')}
        {check('esi_enabled', 'ESI', '0.75% of gross, while gross is 21,000 or less')}
        {check('pt_enabled', 'Professional tax', 'By gross pay, on the state slab')}
      </div>
      <Field label="Professional tax state" htmlFor={`${id}-ptstate`}><Select id={`${id}-ptstate`} value={value.pt_state || 'TS'} onChange={(e) => onChange({ pt_state: e.target.value })} options={STATES} /></Field>
      <Field label="Probation ends" htmlFor={`${id}-prob`} hint="Optional."><Input id={`${id}-prob`} type="date" value={value.probation_end_date ?? ''} onChange={(e) => onChange({ probation_end_date: e.target.value })} /></Field>
      <Field label="Contract ends" htmlFor={`${id}-contract`} hint="Optional. For contract staff."><Input id={`${id}-contract`} type="date" value={value.contract_end_date ?? ''} onChange={(e) => onChange({ contract_end_date: e.target.value })} /></Field>
    </>
  )
}
