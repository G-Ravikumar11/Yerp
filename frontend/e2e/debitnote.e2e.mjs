// A debit note against a supplier bill comes off what is owed on that bill; cancelling it puts the bill back.
// NOT YET RUN: written from backend/tests/test_journals.py and the Journals & Debit Notes page; run it with the rest (npm run e2e).
import { api, launch, open, signIn } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/409 POST \/api\/supplier-debit-notes/] })
await signIn(page)

const stamp = Date.now().toString(36)
const vendor = `E2E Steel ${stamp}`
const bill = (await api(page, 'POST', '/api/bills', { number: `SB-E2E-${stamp}`, vendor_name: vendor, amount: 100000, tax_amount: 18000, total: 118000, status: 'Awaiting Payment' })).data
const owed = async () => (await api(page, 'GET', '/api/money/payables')).data.bills.find((r) => r.id === bill.id)?.outstanding

check('the bill is owed in full to start with', (await owed()) === 118000, String(await owed()))

// --- A debit note cannot take off more than the bill ------------------------------------------------------------------
const tooMuch = await api(page, 'POST', '/api/supplier-debit-notes', { bill_id: bill.id, reason: 'E2E too much', taxable: 200000, tax: 0 })
check('a debit note larger than the bill is refused', tooMuch.status === 409, JSON.stringify(tooMuch.data).slice(0, 100))

// --- Raised: it comes off the bill ------------------------------------------------------------------------------------
const note = (await api(page, 'POST', '/api/supplier-debit-notes', { bill_id: bill.id, reason: 'E2E 2 MT short', taxable: 10000, tax: 1800 })).data
check('the note is numbered DN- and carries the supplier from the bill', /^DN-/.test(note.number) && note.total === 11800 && note.supplier_name === vendor, JSON.stringify(note).slice(0, 140))
check('the bill now owes less by the note', (await owed()) === 106200, String(await owed()))

await open(page, '/money/adjustments')
check('the Debit Notes list shows it', (await page.evaluate(() => document.body.textContent)).includes(note.number))

// --- Cancelled: the bill goes back -----------------------------------------------------------------------------------
const cancelled = (await api(page, 'POST', `/api/supplier-debit-notes/${note.id}/cancel`, { reason: 'E2E supplier agreed' })).data
check('cancelling it marks it cancelled', cancelled.status === 'CANCELLED')
check('and the bill owes in full again', (await owed()) === 118000, String(await owed()))

await done()
