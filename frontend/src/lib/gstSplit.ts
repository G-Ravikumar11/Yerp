/** The GST rates an expense can carry, in percent. */
export const GST_RATES = [0, 5, 12, 18, 28] as const

const paise = (n: number) => Math.round(n * 100) / 100

/** What the tax is inside an amount that already includes it. A supply from another state is IGST at the full rate; a local one is
 * half CGST and half SGST. The server works the same figures out when the entry is saved. */
export function gstSplit(amount: number, rate: number, supply: 'local' | 'non_local') {
  const base = rate ? paise(amount / (1 + rate / 100)) : paise(amount)
  const tax = paise(amount - base)
  if (supply === 'non_local') return { base, tax, igst: tax, cgst: 0, sgst: 0 }
  const cgst = paise(tax / 2)
  return { base, tax, igst: 0, cgst, sgst: paise(tax - cgst) }
}
