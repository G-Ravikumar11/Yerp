// Raise a journal voucher, see it wait in the Approvals inbox (phone and website share it), approve it there.
// NOT YET RUN: written from the backend tests (backend/tests/test_journals.py) and the Approvals screen; run it with the rest (npm run e2e).
import { api, clickText, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/400 POST \/api\/journals/] })
await signIn(page)

const stamp = Date.now().toString(36)
const job = (await api(page, 'POST', '/api/jobs', { name: `E2E journal site ${stamp}` })).data
const jid = job.id ?? job.job?.id
const narration = `E2E short supply written off ${stamp}`
const today = new Date().toISOString().slice(0, 10)
const lines = [
  { kind: 'party', party_type: 'supplier', party_name: 'ACC Ltd', debit: 5000, job_id: jid },
  { kind: 'head', head: 'Site expenses', credit: 5000, job_id: jid },
]

// --- It must balance and say what it is for ---------------------------------------------------------
const unequal = await api(page, 'POST', '/api/journals', { voucher_date: today, narration: 'E2E unequal', lines: [{ ...lines[0], debit: 100 }, { ...lines[1], credit: 90 }] })
check('a journal that does not balance is refused', unequal.status === 400 && /equal/.test(JSON.stringify(unequal.data)))

// --- Raised: it waits for the Master, and is not counted yet -------------------------------------------------------------
const raised = await api(page, 'POST', '/api/journals', { voucher_date: today, narration, lines })
check('a balanced journal is raised and waits for the Master', raised.status === 200 && raised.data.status === 'PENDING', JSON.stringify(raised.data).slice(0, 120))
const number = raised.data.number

await open(page, '/approvals')
await page.waitForFunction((n) => [...document.querySelectorAll('main ul li')].some((li) => li.textContent.includes(n)), { timeout: 15000 }, number)
const card = () => page.$$eval('main ul li', (li) => li.map((x) => x.textContent.replace(/\s+/g, ' ')))
const mine = (await card()).find((t) => t.includes(number)) ?? ''
check('it is in the inbox as a journal voucher with its narration and amount', mine.includes('Journal voucher') && mine.includes(narration) && /5,000/.test(mine), mine.slice(0, 160))

// --- The Master approves it from the inbox ---------------------------------------------------------------------------
const idx = (await card()).findIndex((t) => t.includes(number))
const li = (await page.$$('main ul li'))[idx]
await (await li.$$('button')).at(-1).click() // "Approve"
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Approve')
await waitForToast(page, 'pprove')
await sleep(600)
const after = (await api(page, 'GET', '/api/journals')).data.journals.find((j) => j.number === number)
check('approving it from the inbox approves the journal', after?.status === 'APPROVED', after?.status)
check('what was decided leaves the inbox', !(await card()).some((t) => t.includes(number)))

// --- And it shows on its own page -----------------------------------------------------------------------------------
await open(page, '/money/adjustments')
check('the Journals page lists it', (await page.evaluate(() => document.body.textContent)).includes(number))

await done()
