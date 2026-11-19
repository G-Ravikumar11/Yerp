/* The values the tax selection and the bank transfer details hold, and what they send: apart from the components, which are in TaxFields. */

/** What the tax selection holds: taxable or not, local or non local and from which state, and the GST rate in percent. */
export interface TaxValue { tax: string; supply: string; state: string; rate: string }
export const NO_TAX: TaxValue = { tax: '', supply: '', state: '', rate: '18' }

/** Non taxable is complete on its own; taxable needs local, or non local with the state it comes from. */
export const taxReady = (v: TaxValue) => v.tax === 'non_taxable' || (v.tax === 'taxable' && (v.supply === 'local' || (v.supply === 'non_local' && !!v.state)))

/** What the server is sent for it. */
export const taxPayload = (v: TaxValue) => ({
  tax: v.tax,
  supply: v.tax === 'taxable' ? v.supply : '',
  supply_state: v.tax === 'taxable' && v.supply === 'non_local' ? v.state : '',
  gst_rate: v.tax === 'taxable' ? Number(v.rate) : undefined,
})

/** The tax selection as a value again, from what the server holds (a saved recurring payment being changed). */
export const taxFrom = (r: { tax?: string; supply?: string; supply_state?: string; gst_rate?: number }): TaxValue => ({
  tax: r.tax ?? '', supply: r.supply ?? '', state: r.supply_state ?? '', rate: r.gst_rate ? String(r.gst_rate) : '18',
})

/** Where a bank transfer goes: the payee's bank, its account number and IFSC. */
export interface BankValue { bank: string; account: string; ifsc: string }
export const NO_BANK: BankValue = { bank: '', account: '', ifsc: '' }
export const ifscOk = (s: string) => /^[A-Z]{4}0[A-Z0-9]{6}$/.test(s.trim().toUpperCase())
export const accountOk = (s: string) => /^\d{6,20}$/.test(s.replace(/\s/g, ''))
export const bankReady = (v: BankValue) => !!v.bank.trim() && accountOk(v.account) && ifscOk(v.ifsc)
export const bankPayload = (v: BankValue) => ({ payee_bank: v.bank.trim(), payee_account: v.account.replace(/\s/g, ''), payee_ifsc: v.ifsc.trim().toUpperCase() })
export const bankFrom = (r: { payee_bank?: string; payee_account?: string; payee_ifsc?: string }): BankValue => ({ bank: r.payee_bank ?? '', account: r.payee_account ?? '', ifsc: r.payee_ifsc ?? '' })
