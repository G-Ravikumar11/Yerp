// A bank payment file for supplier bills: written in the bank's layout, then marked paid, which settles the bills.
// NOT YET RUN: written from backend/tests/test_payouts.py and the Bank Payments page; run it with the rest (npm run e2e).
import { api, launch, open, signIn } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/400 POST \/api\/payment-batches/, /409 POST \/api\/payment-batches/] })
await signIn(page)

const stamp = Date.now().toString(36)
const vendor = `E2E Ramco ${stamp}`
const acc = (await api(page, 'POST', '/api/bank-accounts', { name: `E2E HDFC ${stamp}`, kind: 'Bank', opening_balance: 1000000, opening_date: '2026-01-01', account_no: '50200012345678', ifsc: 'HDFC0001234', bank_name: 'HDFC Bank' })).data
await api(page, 'POST', '/api/suppliers', { name: vendor, bank_account: '001105012345', bank_ifsc: 'ICIC0004321', bank_name: 'ICICI Bank', payment_days: 30 })
const mk = async (n, amount, tax) => (await api(page, 'POST', '/api/bills', { number: `SB-E2E-${stamp}-${n}`, vendor_name: vendor, amount, tax_amount: tax, total: amount + tax, status: 'Awaiting Payment' })).data
const big = await mk(1, 250000, 0)
const small = await mk(2, 10000, 1800)

const cands = (await api(page, 'GET', '/api/payment-batches/candidates')).data.items
const pick = cands.filter((c) => [big.id, small.id].includes(c.doc_id))
check('both bills are offered for the file', pick.length === 2, String(pick.length))

// --- The file: one line each, RTGS for the big one and NEFT for the small one ---------------------------------------------
const made = await api(page, 'POST', '/api/payment-batches', { account_id: acc.id, bank_format: 'icici', pay_on: new Date().toISOString().slice(0, 10), items: pick })
check('the file is made and numbered PB-', made.status === 200 && /^PB-/.test(made.data.number) && made.data.count === 2 && made.data.total === 261800, JSON.stringify(made.data).slice(0, 140))
check('the large bill goes by RTGS and the small one by NEFT', new Set(made.data.lines.map((l) => l.mode)).size === 2)

const again = await api(page, 'POST', '/api/payment-batches', { account_id: acc.id, bank_format: 'csv', items: pick.slice(0, 1) })
check('a bill already in an unpaid file is refused a second time', again.status === 409)

await open(page, '/money/bank-payments')
check('the Bank Payments page lists the file', (await page.evaluate(() => document.body.textContent)).includes(made.data.number))

// --- Marked paid: the lines go to PAID and the bills are settled -----------------------------------------------------------
const paid = (await api(page, 'POST', `/api/payment-batches/${made.data.id}/paid`, { paid_on: new Date().toISOString().slice(0, 10), reference: `E2E UTR ${stamp}` })).data
check('marking it paid pays every line and records the payment', paid.status === 'PAID' && paid.lines.every((l) => l.status === 'PAID' && l.entry_id), paid.status)
check('the big bill is now Paid', (await api(page, 'GET', `/api/bills/${big.id}`)).data.status === 'Paid')

await done()
