import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickText, fill, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

// The project BOQ: started for a project, the client's sheet read into the grid, saved with item codes, lines taken
// into a gang order, and tracked.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const xlsx = join(tmpdir(), 'client_boq.xlsx')
execFileSync('python', ['-c', "import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, '.'); from test_boq import sheet, CLIENT_SHEET; open(sys.argv[1], 'wb').write(sheet(CLIENT_SHEET))", xlsx], { cwd: join(import.meta.dirname, '..', '..', 'backend') })

const job = (await api(page, 'POST', '/api/jobs', { name: `BOQ site ${stamp}`, customer_name: 'Kokapet LLP' })).data
const jid = job.id ?? job.job?.id

// --- start the BOQ for the project ---------------------------------------------------------------------------------------
await open(page, '/projects/boq')
await clickText(page, 'main button', 'New BOQ')
await page.waitForSelector('#boq-project')
await page.select('#boq-project', String(jid))
await clickText(page, '[role=dialog] button', 'Open the BOQ')
await page.waitForFunction(() => /\/projects\/boq\/\d+/.test(location.pathname), { timeout: 15000 })
const boq = Number(location_id(page.url()))
function location_id(u) { return u.match(/boq\/(\d+)/)[1] }
await page.waitForFunction(() => /BOQ-\d+/.test(document.querySelector('main h1')?.textContent ?? ''), { timeout: 15000 })
check('a BOQ is opened for the project, as R0', /R0/.test(await page.$eval('main', (m) => m.textContent)))
await page.waitForSelector('input[type=file]', { timeout: 15000 })

// --- the client's sheet is read into the grid -----------------------------------------------------------------------------
await (await page.$('input[type=file]')).uploadFile(xlsx)
await waitForToast(page, '6 line(s) read')
await page.waitForFunction(() => document.body.textContent.includes('Excavation in all types of soil'))
check('the sheet is read into the grid, sections and sub-items included', (await page.$eval('main', (m) => m.textContent)).includes('SUBSTRUCTURE'))
await clickText(page, 'main button', 'Save the BOQ')
await waitForToast(page, '4 item codes given')
const saved = (await api(page, 'GET', `/api/boqs/${boq}`)).data
const priced = saved.lines.filter((l) => l.kind === 'item' || l.kind === 'sub')
check('saved with its total and an item code on every priced line', saved.total === 1472800 && priced.length === 4 && priced.every((l) => l.item_code), String(saved.total))

// --- lines are taken into a gang order ------------------------------------------------------------------------------------
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const order = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: jid, department: vocab.departments[0], subject: `BOQ gang ${stamp}`, commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await open(page, `/subcontractors/work-orders/${order.id}`)
await clickText(page, 'button[role=tab]', 'Schedule')
await clickText(page, 'main button', 'From the project BOQ')
await page.waitForSelector('table[aria-label="Lines of the project BOQ"] input[type=checkbox]')
await page.click('input[aria-label="Take 1.1"]')
await fill(page, 'input[aria-label="Gang rate of 1.1"]', '150')
await fill(page, 'input[aria-label="Quantity of 1.1"]', '300')
await clickText(page, '[role=dialog] button', 'Add 1 line')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await clickText(page, 'main button', 'Save')
await waitForToast(page, 'Saved')
const mine = (await api(page, 'GET', `/api/wo/orders/${order.id}`)).data.order.items
check('the line is in the order and still linked to the BOQ', mine.length === 1 && mine[0].quantity === 300 && mine[0].unit_rate === 150 && mine[0].boq_key === priced[0].key, JSON.stringify(mine[0]))

// --- the tracker adds it up ---------------------------------------------------------------------------------------------------
await open(page, `/projects/boq/${boq}`)
await clickText(page, 'button[role=tab]', 'Tracker')
await page.waitForSelector('table[aria-label="BOQ tracker"] tbody tr')
const text = await page.$eval('table[aria-label="BOQ tracker"]', (t) => t.textContent)
check('the tracker shows what the gang has and what is still without one', text.includes('300') && text.includes('No gang yet') && /16\.7%/.test(text), text.slice(0, 160))

// --- a revision: issue and open the next ---------------------------------------------------------------------------------------
await clickText(page, 'main button', 'New revision')
await page.waitForSelector('#rev-label')
await fill(page, '#rev-label', 'R1 - Award')
await clickText(page, '[role=dialog] button', 'Issue and start the next')
await waitForToast(page, 'is open for changes')
await clickText(page, 'button[role=tab]', 'Revisions')
await page.waitForSelector('table[aria-label="Revisions"] tbody tr')
check('both revisions are listed, the first issued', (await page.$$eval('table[aria-label="Revisions"] tbody tr', (r) => r.length)) === 2)
await done()
