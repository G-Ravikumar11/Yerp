// A member of staff's expense claim: made, approved from the Approvals inbox (where the phone sees it too), then paid.
// NOT YET RUN: written from backend/tests/test_settlement_advances_and_claims.py, test_payouts.py and the Approvals screen; run it with the rest (npm run e2e).
import { api, clickText, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/400 POST \/api\/expense-claims/] })
await signIn(page)

const stamp = Date.now().toString(36)
const emp = (await api(page, 'POST', '/api/employees', { first_name: 'Claim', last_name: `Maker${stamp}`, email: `claim.${stamp}@example.in`, salary: 30000, tax_rate: 0, status: 'active', start_date: '2026-01-01' })).data
const today = new Date().toISOString().slice(0, 10)

const made = await api(page, 'POST', '/api/expense-claims', { spent_on: today, head: 'Travel & conveyance', amount: 450, description: `E2E bus to site ${stamp}`, employee_id: emp.id })
check('a claim is made and waits for accounts', made.status === 200 && made.data.status === 'SUBMITTED' && !!made.data.number, JSON.stringify(made.data).slice(0, 120))
const claim = made.data

// --- It is in the inbox as an expense claim, with the amount and what it was -----------------------------------------------
await open(page, '/approvals')
await page.waitForFunction((n) => [...document.querySelectorAll('main ul li')].some((li) => li.textContent.includes(n)), { timeout: 15000 }, claim.number)
const cards = () => page.$$eval('main ul li', (li) => li.map((x) => x.textContent.replace(/\s+/g, ' ')))
const mine = (await cards()).find((t) => t.includes(claim.number)) ?? ''
check('it shows as an Expense claim with its amount and description', mine.includes('Expense claim') && /450/.test(mine) && mine.includes(`E2E bus to site ${stamp}`), mine.slice(0, 160))

// --- Approve it from the inbox ---------------------------------------------------------------------------------------------
const idx = (await cards()).findIndex((t) => t.includes(claim.number))
await (await (await page.$$('main ul li'))[idx].$$('button')).at(-1).click() // "Approve"
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Approve')
await waitForToast(page, 'pprove')
await sleep(600)
const approved = (await api(page, 'GET', '/api/expense-claims')).data.claims.find((c) => c.id === claim.id)
check('approving it from the inbox approves the claim', approved?.status === 'APPROVED', approved?.status)

// --- Pay it ----------------------------------------------------------------------------------------------------------------
const pay = await api(page, 'POST', '/api/money/entries', { doc_type: 'expense_claim', doc_id: claim.id, amount: 450, paid_on: today, mode: 'Bank transfer' })
check('paying the approved claim is accepted', pay.status === 200, JSON.stringify(pay.data).slice(0, 120))
const settled = (await api(page, 'GET', '/api/expense-claims')).data.claims.find((c) => c.id === claim.id)
check('the claim is settled', settled?.status === 'SETTLED', settled?.status)

await open(page, '/money/expenses?tab=claims')
check('the claims list shows it as settled', (await page.evaluate(() => document.body.textContent)).includes(claim.number))

await done()
