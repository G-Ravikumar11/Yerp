import { api, launch, open, signIn, sleep } from './lib.mjs'

// The company's identity is one record: the sidebar, a notice about what is missing, and the settings checklist all read it.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const set = async (v) => {
  await api(page, 'PUT', `/api/wo/business-units/${unit.id}`, { name: unit.name, code: unit.code, gstin: v.gstin, address: v.address, logo_url: v.logo })
  await api(page, 'PUT', '/api/client/logo', { logo_url: v.logo })
}
const brand = () => page.$eval('a[aria-label="Y ERP home"]', (e) => e.textContent)
const notice = () => page.evaluate(() => [...document.querySelectorAll('[role=note]')].map((e) => e.textContent).find((t) => /Complete company details/.test(t)) || '')

await set({ gstin: '', address: '', logo: '' })
await page.evaluate(() => new Promise((res) => { const r = indexedDB.deleteDatabase('keyval-store'); r.onsuccess = r.onerror = r.onblocked = () => res() }))
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('a[aria-label="Y ERP home"]')
await sleep(1200)
const n1 = await notice()
check('with details missing the owner is told, on any page, what documents lack', /logo/.test(n1), n1.slice(0, 200))
check('the sidebar carries the company name', (await brand()).includes(unit.name), await brand())

await set({ gstin: '36AABCY1234H1ZX', address: 'Plot 12, Madhapur', logo: PNG })
await page.evaluate(() => new Promise((res) => { const r = indexedDB.deleteDatabase('keyval-store'); r.onsuccess = r.onerror = r.onblocked = () => res() }))
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('a[aria-label="Y ERP home"]')
await sleep(1200)
check('once they are given, the notice goes', (await notice()) === '')
check('and the sidebar shows the logo', (await page.$('a[aria-label="Y ERP home"] img[alt$="logo"]')) !== null)

await open(page, '/settings')
await page.waitForSelector('ul[aria-label="Mandatory company details"]')
const list = await page.$eval('ul[aria-label="Mandatory company details"]', (e) => e.textContent)
check('settings lists the mandatory details, none missing', /Company name/.test(list) && /Logo/.test(list) && !/missing/.test(list), list)
await done()
