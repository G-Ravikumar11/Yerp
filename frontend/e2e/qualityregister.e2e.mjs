import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Quality > Register: the form opens, refuses what is missing, saves a real inspection with its photo, shows it, and it is still there afterwards.
const { page, check, done } = await launch({ allow: [/(400|409) POST \/api\/qc\/inspections\/register/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const inDialog = (label) => page.evaluate((label) => {
  const d = [...document.querySelectorAll('[role=dialog]')].pop()
  const b = [...(d?.querySelectorAll('button') ?? [])].find((x) => x.textContent.trim().startsWith(label))
  b?.click()
  return !!b
}, label).then((ok) => { if (!ok) throw new Error(`no button ${label}`) })
const count = async () => (await api(page, 'GET', `/api/qc/inspections?job_id=${job.id}`)).data.total

await open(page, '/projects/quality')
const job = (await api(page, 'POST', '/api/jobs', { name: `Register site ${stamp}`, customer_name: 'E2E' })).data
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForFunction((id) => document.querySelector(`#qc-job option[value="${id}"]`), { timeout: 90000 }, String(job.id))
await setValue(page, '#qc-job', String(job.id))
await sleep(800)

check('the page has a Register button and a separate Export for the spreadsheet', (await text('main')).includes('Register') && (await text('main')).includes('Export'))
await clickText(page, 'main button', 'Register')
await page.waitForSelector('#rg-act')
check('Register opens the registration form', /Register an inspection/.test(await text('[role=dialog]')))
check('the form asks for activity, date, inspector, checklist, result, remarks and status', ['#rg-act', '#rg-date', '#rg-by', '#rg-list', '#rg-def', '#rg-status'].every((s) => true) && (await page.$$eval('#rg-act, #rg-date, #rg-by, #rg-list, #rg-def, #rg-status', (e) => e.length)) === 6 && !!(await page.$('[role=radiogroup][aria-label="Inspection result"]')))
check('the project picker and the checklist items are real data', (await page.$$eval('table[aria-label="Inspection criteria"] tbody tr', (r) => r.length)) > 2)

// refuses what is missing, saving nothing
await fill(page, '#rg-by', '')
await inDialog('Register inspection')
await sleep(300)
const t = await text('[role=dialog]')
check('an empty form is refused, naming what is missing', /Which activity or work item/.test(t) && /Who carried out/.test(t))
check('and nothing was saved', (await count()) === 0)

// a failed inspection with a defect and a photo
await fill(page, '#rg-act', `Raft reinforcement ${stamp}`)
await fill(page, '#rg-by', 'R. Kumar')
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] input[name=rg-result]')][1].click())      // Pass: ticks every check ok
await page.evaluate(() => document.querySelectorAll('table[aria-label="Inspection criteria"] tbody tr')[2].querySelectorAll('input[type=radio]')[1].click())   // one not ok
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] input[name=rg-result]')][2].click())      // Fail
await fill(page, '#rg-def', 'Lap length short at grid C-D')
check('choosing Fail offers Failed (and Awaiting Approval) as the status', (await page.$$eval('#rg-status option', (o) => o.map((x) => x.textContent))).join() === 'Failed,Awaiting Approval')
const png = join(tmpdir(), `defect-${stamp}.png`)
writeFileSync(png, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64'))
await (await page.$('input[aria-label="Attach photos or documents"]')).uploadFile(png)
await page.waitForFunction(() => document.querySelector('[role=dialog] button[aria-label^="Remove defect"]'), { timeout: 5000 })
check('a photo can be attached', true)
// a double click is one record
await page.evaluate(() => { const b = [...document.querySelectorAll('[role=dialog] button')].find((x) => x.textContent.trim().startsWith('Register inspection')); b.click(); b.click() })
await waitForToast(page, 'registered')
check('the success message is shown once the server has saved it', /INS-\d+ registered - failed/.test(await page.evaluate(() => document.querySelector('[aria-live=polite]')?.textContent ?? '')))
await toastsGone(page)
await page.waitForFunction(() => /Raft reinforcement/.test(document.querySelector('[role=dialog]')?.textContent ?? ''), { timeout: 10000 })
check('the saved inspection opens with its details', /Raft reinforcement/.test(await text('[role=dialog]')) && /Failed/.test(await text('[role=dialog]')) && /R\. Kumar/.test(await text('[role=dialog]')) && /Lap length short/.test(await text('[role=dialog]')))
check('exactly one record was created', (await count()) === 1)
const saved = (await api(page, 'GET', `/api/qc/inspections?job_id=${job.id}`)).data.inspections[0]
check('it is in the database with its result, date, inspector and activity', saved.result === 'FAILED' && saved.inspected_by === 'R. Kumar' && saved.work_activity === `Raft reinforcement ${stamp}` && saved.inspected_on.length === 10 && saved.failed_items === 1)
const files = (await api(page, 'GET', `/api/files?attached_type=inspection&attached_id=${saved.id}`)).data
check('and the photo is stored against it', JSON.stringify(files).includes('defect-'), JSON.stringify(files).slice(0, 80))
await page.keyboard.press('Escape')
await sleep(500)
check('the list shows it at once', /Raft reinforcement/.test(await text('table[aria-label=Inspections] tbody')) && /Failed/.test(await text('table[aria-label=Inspections] tbody')))

// it survives a reload and a fresh sign-in
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await api(page, 'POST', '/api/client/logout')
await page.goto((await page.evaluate(() => location.origin)) + '/next/login', { waitUntil: 'domcontentloaded' })
await signIn(page)
await open(page, '/projects/quality')
await page.waitForFunction((id) => document.querySelector(`#qc-job option[value="${id}"]`), { timeout: 90000 }, String(job.id))
await setValue(page, '#qc-job', String(job.id))
await page.waitForFunction(() => /Raft reinforcement/.test(document.querySelector('table[aria-label=Inspections] tbody')?.textContent ?? ''), { timeout: 20000 })
check('after logging out and in again the record is still there', true)

// a backend refusal is shown, not swallowed
const refused = await api(page, 'POST', '/api/qc/inspections/register', { job_id: job.id, work_activity: 'x', inspector: 'y', inspected_on: '2999-01-01', checklist: 'Plastering', result: '', status: 'Pending' })
check('the server refuses a future date with its own message', refused.status === 400 && /future/.test(refused.data.detail), refused.data.detail)
await done()
