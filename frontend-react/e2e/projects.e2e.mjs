import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Projects: create one with its site location, see it on the board, open it, change it.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const name = `QA Fairview ${stamp}`
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const gone = () => page.waitForFunction(() => !document.querySelector('[role=dialog]'), { timeout: 10000 })
const row = () => page.evaluate((n) => [...document.querySelectorAll('table[aria-label=Projects] tbody tr')].find((r) => r.textContent.includes(n))?.textContent.replace(/\s+/g, ' '), name)

await open(page, '/projects')
await page.waitForSelector('table[aria-label=Projects]')
check('the board shows the totals', (await text('main')).includes('Invoiced') && (await text('main')).includes('Profit'))
await clickText(page, 'main button', 'New project')
await page.waitForSelector('#pj-name')
await fill(page, '#pj-name', name)
await fill(page, '#pj-cust', 'QA Client Ltd')
await setValue(page, '#pj-status', 'won')
await fill(page, '#pj-quoted', '500000')
await fill(page, '#pj-budget', '400000')
await page.waitForFunction(() => document.querySelector('#pj-state option[value="36"]'), { timeout: 8000 })
await setValue(page, '#pj-state', '36')
await fill(page, 'input[aria-label="Site location"]', '17.4239, 78.3413')
await clickText(page, '[role=dialog] button', 'Save project')
await waitForToast(page, 'Project created')
await gone()
await sleep(700)
check('the project is on the board with its status and customer', /Won/.test(await row()) && /QA Client/.test(await row()), await row())
await toastsGone(page)

const id = (await api(page, 'GET', '/api/jobs-summary')).data.jobs.find((j) => j.name === name).id
const loc = (await api(page, 'GET', `/api/jobs/${id}/site-location`)).data
check('its site location and state were kept', loc.set === true && Math.abs(loc.lat - 17.4239) < 0.001 && (await api(page, 'GET', `/api/jobs/${id}`)).data.state_code === '36', JSON.stringify(loc))

await page.evaluate((n) => [...document.querySelectorAll('table[aria-label=Projects] tbody tr')].find((r) => r.textContent.includes(n)).click(), name)
await page.waitForFunction((n) => document.querySelector('main h1')?.textContent.includes(n), { timeout: 8000 }, name)
check('opening it shows where the money stands', (await text('main')).includes('Quoted') && (await text('main')).includes('Cost so far') && (await text('main')).includes('Nothing filed against this project yet'))
await clickText(page, 'main button', 'Edit')
await page.waitForSelector('#pj-name')
await fill(page, '#pj-budget', '450000')
await fill(page, 'input[aria-label="Site location"]', '')
await clickText(page, '[role=dialog] button', 'Save project')
await waitForToast(page, 'Project updated')
await gone()
await sleep(600)
check('editing it saves the budget, and clearing the location takes it off', (await api(page, 'GET', `/api/jobs/${id}`)).data.budget === 450000 && (await api(page, 'GET', `/api/jobs/${id}/site-location`)).data.set === false)
await done()
