import { api, approvedOrder, clickText, launch, open, signIn, sleep } from './lib.mjs'

// An order is worked through in steps: Next and Back under each section, and a tab of what follows once it is live.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const draft = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: vocab.jobs[0].id, department: 'Civil', subject: 'Steps', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order

const tabs = () => page.$$eval('[role=tab][aria-selected=true]', (t) => t.map((e) => e.textContent)).then((t) => t.join('|'))
await open(page, `/subcontractors/work-orders/${draft.id}`)
await page.waitForSelector('nav[aria-label="Order steps"], [aria-label="Order steps"]')
check('a draft has no After approval tab yet', !(await page.$$eval('[role=tab]', (t) => t.some((e) => /After approval/.test(e.textContent)))))
check('the first step offers Next, not Back', !(await page.evaluate(() => /Back:/.test(document.querySelector('[aria-label="Order steps"]').textContent))) && /Next: Schedule/.test(await page.$eval('[aria-label="Order steps"]', (e) => e.textContent)))
await clickText(page, '[aria-label="Order steps"] button', 'Next')
await sleep(500)
check('Next moves to the Schedule', /Schedule/.test(await tabs()), await tabs())
await clickText(page, '[aria-label="Order steps"] button', 'Next')
await sleep(300)
await clickText(page, '[aria-label="Order steps"] button', 'Next')
await sleep(300)
check('and on to Approval, where there is no Next on a draft', /Approval/.test(await tabs()) && !(await page.$eval('[aria-label="Order steps"]', (e) => /Next:/.test(e.textContent))))
await clickText(page, '[aria-label="Order steps"] button', 'Back')
await sleep(300)
check('Back returns to Conditions', /Conditions/.test(await tabs()), await tabs())

// Once live, a tab for what follows.
const o = await approvedOrder(page, { subject: 'Live steps' })
await open(page, `/subcontractors/work-orders/${o.id}`)
await page.waitForSelector('[role=tab]')
await clickText(page, '[role=tab]', 'After approval')
await page.waitForSelector('[aria-label="Steps after approval"]')
const t = await page.$eval('[aria-label="Steps after approval"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('it lists approved, counter-signed, measure, bill and pay', /Approved/.test(t) && /Counter-signed/.test(t) && /Measure the work/.test(t) && /Bill what is measured/.test(t) && /Certify and pay/.test(t), t.slice(0, 200))
const href = await page.$eval('[aria-label="Steps after approval"] a[href*="measurement-book"]', (a) => a.getAttribute('href'))
check('the measure step opens this order in the Measurement Book', href.includes(`order=${o.id}`), href)
await done()
