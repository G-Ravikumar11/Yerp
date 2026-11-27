import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { BASE, api, clickText, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

// The whole website flow, as the Master does it in Settings -> Website and as a visitor sees it:
//   a heading and a picture changed, checked in both previews, published, seen on the live site; the old version put back;
//   a job posted and seen on the site; an enquiry sent from the site and found as a lead; the site on a phone, light and
//   dark. Run against a throwaway database (it publishes and posts for real). SHOTS=<folder> keeps a screenshot of each step.
const SHOTS = process.env.SHOTS || ''
const { page, browser, check, done } = await launch({ width: 1440, height: 1000 })
const shot = async (p, name) => { if (SHOTS) await p.screenshot({ path: join(SHOTS, name + '.png'), fullPage: name.includes('full') }) }
const byLabel = (label, within = 'main') => page.evaluate((l, w) => {
  const el = [...document.querySelectorAll(`${w} label`)].find((x) => x.textContent.trim().startsWith(l))
  return el?.htmlFor ? '#' + CSS.escape(el.htmlFor) : null
}, label, within)
const type = async (label, value, within = 'main') => {
  const sel = await byLabel(label, within)
  if (!sel) throw new Error('No field labelled ' + label)
  await page.click(sel, { clickCount: 3 })
  await page.keyboard.press('Backspace')
  await page.type(sel, value)
}
const part = async (name) => { await clickText(page, 'nav[aria-label="Parts of the website"] button', name); await sleep(400) }
const frame = (title) => page.$(`iframe[title="${title}"]`).then((h) => h.contentFrame())
const publish = async () => {
  await clickText(page, 'button', 'Publish')
  await page.waitForSelector('[role=dialog]')
  await clickText(page, '[role=dialog] button', 'Publish')
  await waitForToast(page, 'Published')
}
const stamp = Date.now().toString().slice(-5)
const visitor = await browser.createBrowserContext()
const site = await visitor.newPage()
const visit = async ({ width = 390, height = 844, dark = false } = {}) => {
  await site.setViewport({ width, height, isMobile: width < 600, hasTouch: width < 600 })
  await site.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }])
  await site.goto(BASE + '/', { waitUntil: 'networkidle0' })
  await sleep(700)
}
const heading = (id) => site.$eval(`#${id} h2`, (e) => e.textContent).catch(() => null)

await signIn(page)
await open(page, '/website')
await page.waitForSelector('nav[aria-label="Parts of the website"]')
check('the panel opens on its Overview checklist', !!(await page.$('[aria-label="Checklist"]')))
await sleep(2500)                                          // the two preview frames load the site

// --- 1. A heading and a picture, changed in the panel --------------------------------------------------------
const title = `How we build, step by step ${stamp}`
await part('How we build')
await type('Heading', title)
const png = await page.evaluate(() => {
  const c = document.createElement('canvas'); c.width = 2400; c.height = 1600
  const g = c.getContext('2d'); const grad = g.createLinearGradient(0, 0, 2400, 1600)
  grad.addColorStop(0, '#005596'); grad.addColorStop(1, '#1a8ae1'); g.fillStyle = grad; g.fillRect(0, 0, 2400, 1600)
  g.fillStyle = '#fff'; g.font = 'bold 150px sans-serif'; g.fillText('Our site', 700, 860)
  return c.toDataURL('image/png').split(',')[1]
})
const file = join(tmpdir(), `website-${stamp}.png`)
writeFileSync(file, Buffer.from(png, 'base64'))
await part('Pictures')
await page.select('#pic-where', 'cap:0')                   // "What we build": the first kind of work
const [chooser] = await Promise.all([page.waitForFileChooser(), clickText(page, 'main button', 'Choose a photo')])
await chooser.accept([file])
await page.waitForSelector('[role=dialog] [aria-label="Zoom"]')
await sleep(400)
await shot(page, '1-crop')
await clickText(page, '[role=dialog] button', 'Use this picture')
await waitForToast(page, 'Picture uploaded')
const picture = (await api(page, 'GET', '/api/website/images')).data.images[0]
check('the picture is cropped to the section shape and made small for the web', picture.place === 'section' && picture.size < 300 * 1024, `${picture.size} bytes`)

// --- 2. The preview shows it, at a desktop's width and a phone's ---------------------------------------------
await sleep(900)
for (const t of ['Preview of the draft on a desktop screen', 'Preview of the draft on a phone']) {
  const f = await frame(t)
  const where = t.split(' on ')[1]
  check(`the ${where} preview shows the new heading`, (await f.$eval('#process h2', (e) => e.textContent)) === title)
  check(`the ${where} preview shows the new picture`, await f.$$eval('#build img', (imgs, p) => imgs.some((i) => i.src.endsWith(p)), picture.path))
}
await page.$eval('section[aria-label="Preview of the draft"]', (e) => e.scrollIntoView())
await sleep(500)
await shot(page, '2-preview')
await visit({ width: 1280, height: 900 })
check('visitors do not see the draft', (await heading('process')) !== title)
check('nor its picture', (await fetch(BASE + picture.path)).status === 404)

// --- 3. Published: the live site changes -----------------------------------------------------------------------
await publish()
await visit({ width: 1280, height: 900 })
check('the live site shows the new heading', (await heading('process')) === title)
check('and the new picture', await site.$$eval('#build img', (imgs, p) => imgs.some((i) => i.src.endsWith(p)), picture.path))

// --- 4. The old version put back --------------------------------------------------------------------------------
await part('History')
await sleep(600)
await shot(page, '3-history')
const versions = (await api(page, 'GET', '/api/website/versions')).data.versions
await page.evaluate((n) => {
  const row = [...document.querySelectorAll('[aria-label="Published versions"] li')].find((li) => li.textContent.includes(`Version ${n}`))
  row.querySelector('button').click()
}, versions[1]?.number ?? 0)
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Restore this version')
await waitForToast(page, 'Restored version')
await visit({ width: 1280, height: 900 })
check('after the restore the old heading is back on the live site', (await heading('process')) !== title, await heading('process'))

// --- 5. A job posted from the panel is on the site, and its form takes an application ------------------------
await part('Careers')
await clickText(page, 'main button', 'Post an opening')
await page.waitForSelector('[role=dialog] #op-title')
await page.type('#op-title', `Site Engineer ${stamp}`)
await page.type('#op-loc', 'Ongole, Andhra Pradesh')
await page.type('#op-exp', '3-5 years')
await page.type('#op-desc', 'Runs a block of the APTIDCO housing site: shuttering, steel and concrete.')
await clickText(page, '[role=dialog] button', 'Post on the website')
await waitForToast(page, 'is posted on the website')
await visit()
const job = await site.$$eval('.job', (jobs, t) => jobs.map((j) => ({ t: j.querySelector('h3').textContent, href: j.querySelector('a')?.getAttribute('href') })).find((j) => j.t === t), `Site Engineer ${stamp}`)
check('the job is on the site\'s Careers section, on a phone', !!job, JSON.stringify(job))
await site.$eval('#careers', (e) => e.scrollIntoView())
await sleep(400)
await shot(site, '4-careers-phone')
await site.goto(BASE + job.href, { waitUntil: 'networkidle0' })
check('its Apply opens the application form', (await site.content()).includes('Full name'))

// --- 6. An enquiry from the website arrives as a lead ----------------------------------------------------------
await visit({ width: 1280, height: 900 })
const who = `Website Test ${stamp}`
await site.$eval('#enquire', (e) => e.scrollIntoView())
await site.type('#enquire input[name=name]', who)
await site.type('#enquire input[name=phone]', '9800000000')
await site.type('#enquire input[name=city]', 'Hyderabad')
await site.type('#enquire textarea[name=message]', 'A test enquiry from the website check. Please ignore.')
await site.click('#enquire button[type=submit]')
await site.waitForFunction(() => /we have your enquiry/i.test(document.querySelector('.enq__done')?.textContent ?? ''), { timeout: 8000 })
const leads = (await api(page, 'GET', '/api/leads')).data.leads
const lead = leads.find((l) => l.contact_person === who)
check('the enquiry arrives as a new lead in the Tender Pipeline', !!lead && lead.source === 'Website enquiry' && lead.status === 'NEW', JSON.stringify(lead ?? {}).slice(0, 160))

// --- 6b. The projects page, and the edit bar for whoever may edit ---------------------------------------------
await site.goto(BASE + '/projects', { waitUntil: 'networkidle0' })
check('the projects page draws every sheet', (await site.$$('.psheet')).length >= 2)
const editor = await browser.newPage()
await editor.goto(BASE + '/', { waitUntil: 'networkidle0' })          // signed in, as the Master
check('the Master sees the edit bar on the public page', !!(await editor.$('.editbar a[href$="/website"]')))
check('a visitor does not', !(await site.$('.editbar')))
await editor.close()

// --- 7. The site on a phone, light and dark --------------------------------------------------------------------
for (const dark of [false, true]) {
  await visit({ dark })
  const mode = dark ? 'dark' : 'light'
  check(`on a phone (${mode}) nothing scrolls sideways`, await site.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  const bg = await site.evaluate(() => getComputedStyle(document.body).backgroundColor)
  // Look B: paper (#f7f9fb) by day, blueprint (#0a2442) by night.
  check(`the page is ${mode}`, bg === (dark ? 'rgb(10, 36, 66)' : 'rgb(247, 249, 251)'), bg)
  await shot(site, `5-phone-${mode}-full`)
}
await visit({ width: 1440, height: 900, dark: true })
await shot(site, '6-desktop-dark')
await visit({ width: 1440, height: 900 })
await shot(site, '7-desktop-light-full')

await visitor.close()
await done()
