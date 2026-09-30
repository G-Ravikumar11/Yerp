import { launch, open, signIn, sleep, BASE, clickText, waitForToast } from './lib.mjs'

// Going offline makes the browser log failed requests; that is the point of the test.
const { page, check, done } = await launch({ allow: [/net::ERR|Failed to fetch/i] })
await signIn(page)

// --- The app installs itself on the device ---------------------------------------------
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('table[aria-label="Work orders"]')
const worker = await page.evaluate(async () => {
  const reg = await navigator.serviceWorker.ready
  return { scope: reg.scope, active: !!reg.active }
})
check('a service worker is installed, scoped to the app', worker.active && worker.scope.endsWith('/next/'), worker.scope)
await page.waitForFunction(async () => (await caches.keys()).some((k) => k.includes('precache')), { timeout: 15000 })
check('the app shell is cached on the device', true)
const manifestOk = await page.evaluate(async () => {
  const link = document.querySelector('link[rel=manifest]')
  const res = await fetch(link.href)
  const m = await res.json()
  return { type: res.headers.get('content-type'), name: m.short_name, icons: m.icons.length }
})
check('the page links a valid manifest', /manifest\+json/.test(manifestOk.type) && manifestOk.name === 'Y ERP' && manifestOk.icons >= 3, JSON.stringify(manifestOk))

// --- Read a few screens so there is something to keep --------------------------------------
await open(page, '/')
await page.waitForFunction(() => document.querySelectorAll('figure svg').length >= 3, { timeout: 15000 })
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('table[aria-label="Work orders"] tbody tr')
const rowsOnline = await page.$$eval('table[aria-label="Work orders"] tbody tr', (r) => r.length)
await sleep(3000) // the cache is written to the device a moment after each read
const kept = await page.evaluate(
  () =>
    new Promise((resolve) => {
      const open = indexedDB.open('keyval-store')
      open.onsuccess = () => {
        const get = open.result.transaction('keyval').objectStore('keyval').get('yerp-query-cache')
        get.onsuccess = () => resolve(!!get.result)
        get.onerror = () => resolve(false)
      }
      open.onerror = () => resolve(false)
    }),
)
check('what was read is kept on the device', kept)

// --- Lose the signal, reload ---------------------------------------------------------------------------
await page.setOfflineMode(true)
await page.evaluate(() => window.dispatchEvent(new Event('offline')))
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForSelector('main h1', { timeout: 15000 })
await sleep(1500)
check('the app opens with no signal', (await page.$eval('main h1', (e) => e.textContent)).includes('Work Orders'))
const rowsOffline = await page.$$eval('table[aria-label="Work orders"] tbody tr', (r) => r.length)
check('and shows the last-known work orders', rowsOffline === rowsOnline && rowsOffline > 0, `${rowsOffline} of ${rowsOnline}`)
check('the person is still recognised (not sent to sign in)', (await page.$eval('header', (e) => e.textContent)).includes('Owner') && !page.url().includes('login'))
check('the top bar says it is offline', (await page.$eval('header', (e) => e.textContent)).includes('Offline'))

await page.goto(BASE + '/next/subcontractors/measurement-book', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('main h1', { timeout: 15000 })
check('another screen opens offline too (the shell is not tied to one route)', (await page.$eval('main h1', (e) => e.textContent)).includes('Measurement Book'))

// --- Signal back ----------------------------------------------------------------------------------------------
await page.setOfflineMode(false)
await page.evaluate(() => window.dispatchEvent(new Event('online')))
await sleep(1500)
check('back online, the bar goes quiet', !(await page.$eval('header', (e) => e.textContent)).includes('Offline'))

// --- Signing out leaves nothing behind --------------------------------------------------------------------------
await page.evaluate(() => document.querySelector('[aria-label="Sign out"]').click())
await page.waitForFunction(() => location.pathname.includes('login'), { timeout: 15000 })
const left = await page.evaluate(
  () =>
    new Promise((resolve) => {
      const open = indexedDB.open('keyval-store')
      open.onsuccess = () => {
        const get = open.result.transaction('keyval').objectStore('keyval').get('yerp-query-cache')
        get.onsuccess = () => resolve(!!get.result)
        get.onerror = () => resolve(false)
      }
      open.onerror = () => resolve(false)
    }),
)
check('signing out clears what the device was keeping for them', !left)

await done()
