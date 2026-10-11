import { api, clickText, launch, open, signIn, waitForToast } from './lib.mjs'

// A variation to the BOQ: raised, sent up the route, seen in the approvals inbox, approved - and the BOQ moves on.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const job = (await api(page, 'POST', '/api/jobs', { name: `Variation site ${stamp}`, customer_name: 'Kokapet LLP' })).data
const jid = job.id ?? job.job?.id
const boq = (await api(page, 'POST', '/api/boqs', { job_id: jid })).data.boq
const lines = [
  { kind: 'section', sno: 'A', description: 'SUBSTRUCTURE' },
  { kind: 'item', sno: '1.1', description: `Excavation ${stamp}`, uom: 'cum', quantity: 500, rate: 180 },
  { kind: 'item', sno: '1.2', description: `RCC in raft ${stamp}`, uom: 'cum', quantity: 120, rate: 8200 },
]
const saved = (await api(page, 'PUT', `/api/boqs/${boq.id}/lines`, { lines, issue_codes: true })).data
const key = saved.lines.find((l) => l.sno === '1.1').key
const v = (await api(page, 'POST', '/api/boq-variations', { boq_id: boq.id, reason: 'Rock found at 2 m', lines: [
  { kind: 'quantity', boq_key: key, change_qty: 80 },
  { kind: 'extra', description: `Rock breaking ${stamp}`, uom: 'cum', change_qty: 25, rate: 1800, sno: '1.9', section_key: saved.lines[0].key },
] })).data.variation

await open(page, `/projects/boq/${boq.id}?tab=variations`)
await page.waitForSelector('table[aria-label="Variations"] tbody tr')
check('the variation is listed with what it adds', /BV-01/.test(await page.$eval('table[aria-label="Variations"]', (t) => t.textContent)) && /59,400/.test(await page.$eval('table[aria-label="Variations"]', (t) => t.textContent)))

// --- open it and send it ----------------------------------------------------------------------------------------------------
await page.click('table[aria-label="Variations"] tbody tr')
await page.waitForSelector('[role=dialog]')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('Rock found at 2 m'))
check('the dialog shows what it adds and who it waits for', /59,400/.test(await page.$eval('[role=dialog]', (d) => d.textContent)), (await page.$eval('[role=dialog]', (d) => d.textContent)).slice(-160))
await clickText(page, '[role=dialog] button', 'Send for approval')
await waitForToast(page, 'now submitted')
const inbox = (await api(page, 'GET', '/api/approvals/inbox')).data.items.filter((i) => i.kind === 'boq_variation')
check('it waits in the approvals inbox', inbox.length === 1 && inbox[0].number === v.number && inbox[0].doc_id === boq.id, JSON.stringify(inbox.map((i) => i.number)))

// --- approve it from the screen -------------------------------------------------------------------------------------------------
await open(page, `/projects/boq/${boq.id}?tab=variations`)
await page.waitForSelector('table[aria-label="Variations"] tbody tr')
await page.click('table[aria-label="Variations"] tbody tr')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Approve')
await waitForToast(page, 'now approved')
const book = (await api(page, 'GET', `/api/boqs/${boq.id}`)).data
const now = Object.fromEntries(book.lines.map((l) => [l.sno, l]))
check('the BOQ is now its next revision, with the changes in it', book.boq.current_rev === 1 && now['1.1'].quantity === 580 && now['1.9']?.quantity === 25 && !!now['1.9'].item_code, JSON.stringify(book.boq))
check('the old revision is left as it was', (await api(page, 'GET', `/api/boqs/${boq.id}?rev=0`)).data.total === 500 * 180 + 120 * 8200)
await open(page, `/projects/boq/${boq.id}?tab=variations`)
await page.waitForSelector('table[aria-label="Variations"] tbody tr')
check('the list says which revision it made', /made R1/.test(await page.$eval('table[aria-label="Variations"]', (t) => t.textContent)))

// --- a new one can be started from the screen -----------------------------------------------------------------------------------
await clickText(page, 'main button', 'New variation')
await page.waitForSelector('[role=dialog] table, [role=dialog] [role=grid]')
await clickText(page, '[role=dialog] button', 'Add what has been executed past the BOQ')
await waitForToast(page, 'Nothing has been executed past the BOQ')
check('nothing is suggested when nothing has run past the BOQ', true)
await done()
