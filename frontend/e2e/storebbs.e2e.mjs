import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// The old store as a record, item duplicates and merging, shuttering and scaffolding hire, and the Bar Bending Schedule,
// each through its screen and checked against what the server then holds.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/(items|material-vouchers)/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const clear = () => toastsGone(page).catch(() => {})
const dialog = () => text('[role=dialog]')
const pick = (sel, re) => page.$eval(sel, (s, re) => [...s.options].find((o) => new RegExp(re).test(o.textContent))?.value, re).then((v) => setValue(page, sel, v))

// the old store
await open(page, '/store/old/material-vouchers')
check('the voucher screen says it is read-only', /legacy store module\. Transactions are available in read-only mode/.test(await text('main')))
check('it offers no new voucher', !/Save the voucher|New voucher/.test(await text('main')))
for (const path of ['/store/old/stock', '/store/old/goods-receipt']) {
  await open(page, path)
  check(`${path} is read-only`, /read-only mode/.test(await text('main')) && !/Issue to site|Receive a delivery/.test(await text('main')))
}
const job = (await api(page, 'GET', '/api/jobs')).data
const projects = job.jobs ?? job
const j = (await api(page, 'POST', '/api/jobs', { name: `Store site ${stamp}`, customer_name: 'E2E' })).data
const refused = await api(page, 'POST', '/api/material-vouchers', { job_id: j.id, lines: [{ description: 'Cement', issued_qty: 1 }] })
check('a voucher sent straight to the server is refused', refused.status === 409, String(refused.status))

// items
const name = `QA Cement ${stamp}`
const a = (await api(page, 'POST', '/api/items', { item_name: name, units_of_measure: 'Bag', kind: 'RM' })).data.item
const twice = await api(page, 'POST', '/api/items', { item_name: `  ${name.toUpperCase()} `, units_of_measure: 'Bag', kind: 'RM' })
check('the same item in another case is refused and named', twice.status === 409 && twice.data.detail.includes(a.item_code), JSON.stringify(twice.data).slice(0, 90))
const other = (await api(page, 'POST', '/api/items', { item_name: `${name} X`, units_of_measure: 'Bag', kind: 'RM' })).data.item
await api(page, 'PUT', `/api/items/${other.id}`, { ...other, item_name: `${name} X` })
await open(page, '/store/items')
check('the item master links to duplicates', /Duplicates/.test(await text('main')))
await open(page, '/store/items/duplicates')
check('the duplicate report opens', /exact/.test(await text('main')) && /possible/.test(await text('main')), (await text('main')).slice(0, 120))
await api(page, 'POST', '/api/items', { item_name: `Paint, white ${stamp}`, units_of_measure: 'Nos', kind: 'RM' })
await api(page, 'POST', '/api/items', { item_name: `White paint ${stamp}`, units_of_measure: 'Nos', kind: 'RM' })
await open(page, `/store/items/duplicates?x=${stamp}`)
await fill(page, '[aria-label="Search duplicates"]', `paint ${stamp}`)
await sleep(1200)
await fill(page, '[aria-label="Search duplicates"]', stamp)
await sleep(1500)
check('the two are found as a possible match', /Possible/.test(await text('main')) && new RegExp(`White paint ${stamp}`).test(await text('main')), (await text('main')).slice(150, 330))
await clickText(page, 'main button', 'Merge')
await page.waitForSelector('[role=dialog] section')
await sleep(800)
check('merge shows the items side by side with their stock and links', (await page.$$('[role=dialog] section')).length === 2 && /Linked records/.test(await dialog()))
await clickText(page, '[role=dialog] button', 'Continue')
await page.waitForSelector('#mg-why')
check('it asks once more before merging', /cannot be undone/.test(await dialog()))
await fill(page, '#mg-why', 'Same paint')
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => b.textContent.includes('Yes, merge')).click())
await waitForToast(page, 'merged into')
await sleep(900)
const left = (await api(page, 'GET', `/api/items/duplicates?q=${stamp}`)).data
check('after the merge they are no longer listed', left.total === 0, String(left.total))
await clear()

// hire
const prov = (await api(page, 'POST', '/api/plant/rental-providers', { name: `Forms ${stamp}` })).data.provider
await api(page, 'POST', '/api/plant/formwork', { job_id: j.id, kind: 'Shuttering', provider_id: prov.id, description: `Plates ${stamp}`, quantity: 100, uom: 'Sqm', start_date: day(-9), expected_return: day(20), daily_rate: 5, replacement_cost: 400 })
await open(page, '/projects/equipment?tab=formwork')
await page.waitForFunction((s) => document.querySelector('main')?.textContent.includes(s), { timeout: 15000 }, `Plates ${stamp}`)
await page.evaluate((s) => [...[...document.querySelectorAll('table[aria-label="Shuttering and scaffolding hires"] tbody tr')].find((r) => r.textContent.includes(s)).querySelectorAll('button')].find((b) => b.textContent.trim() === 'Return').click(), `Plates ${stamp}`)
await page.waitForSelector('#fr-back')
await fill(page, '#fr-back', '40')
await fill(page, '#fr-lost', '10')
await clickText(page, '[role=dialog] button', 'Work out the charges')
await page.waitForSelector('[aria-label=Charges]')
const ch = await text('[aria-label=Charges]')
check('the return shows hire and replacement apart, from the server', /2,500/.test(ch) && /4,000/.test(ch) && /6,500/.test(ch), ch)
await clickText(page, '[role=dialog] button', 'Confirm the return')
await waitForToast(page, 'Return recorded')
await sleep(900)
const h = (await api(page, 'GET', `/api/plant/formwork?job_id=${j.id}`)).data.hires[0]
check('partly returned, with the rest running', h.status === 'Partially returned' && h.out === 50 && h.loss_charge === 4000, JSON.stringify([h.status, h.out]))
check('the report shows the project', /Hire by project/.test(await text('main')))
await clear()

// BBS
await open(page, '/projects/bbs')
await clickText(page, 'main button', 'Bar mark')
await page.waitForSelector('#bb-block')
await page.waitForFunction((s) => [...document.querySelectorAll('#bb-job option')].some((o) => o.textContent.includes(s)), { timeout: 15000 }, `Store site ${stamp}`)
await pick('#bb-job', `Store site ${stamp}`)
await fill(page, '#bb-block', 'A')
await fill(page, '#bb-floor', 'First')
await fill(page, '#bb-mem', 'B1')
await fill(page, '#bb-mark', 'a1')
await fill(page, '#bb-dia', '16')
await fill(page, '#bb-num', '10')
await fill(page, '#bb-dA', '6000')
await page.waitForSelector('[aria-label="Worked out"]', { timeout: 8000 })
await sleep(500)
const fig = await text('[aria-label="Worked out"]')
check('the figures come from the server as typed', /60\.000 m/.test(fig) && /1\.580 kg\/m/.test(fig) && /94\.815 kg/.test(fig), fig)
await clickText(page, '[role=dialog] button', 'Save')
await waitForToast(page, 'saved')
await sleep(900)
const list = (await api(page, 'GET', `/api/bbs?job_id=${j.id}`)).data
check('it is saved with its weight', Math.abs(list.entries[0].total_weight_kg - 94.81481) < 0.001 && list.entries[0].status === 'Draft')
await page.evaluate(() => [...document.querySelectorAll('table[aria-label="Bar marks"] button')].find((b) => b.textContent.trim() === 'Approve').click())
await waitForToast(page, 'approved')
await sleep(700)
check('approved on the screen', /Approved/.test(await text('table[aria-label="Bar marks"]')))
check('the summary is there', /By diameter/.test(await text('main')) && /By floor and element/.test(await text('main')))

await page.setViewport({ width: 390, height: 800 })
for (const path of ['/projects/bbs', '/store/items/duplicates', '/projects/equipment?tab=formwork']) {
  await open(page, path)
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check(`${path} fits a phone`, over <= 1, String(over))
}
console.log('projects read:', Array.isArray(projects))
await done()
