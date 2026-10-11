import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/400 POST \/api\/wo\/contractors/] })
await signIn(page)
await open(page, '/subcontractors/vendors')
await page.waitForSelector('table[aria-label=Vendors] tbody tr')
const rows = () => page.$$eval('table[aria-label=Vendors] tbody tr', (r) => r.length)
const before = await rows()
check('the register lists gangs with their vendor codes', before > 0 && /[A-Z]{2}-?\d+/.test(await page.$eval('table[aria-label=Vendors] tbody tr td:nth-child(2)', (e) => e.textContent)), `${before} vendors`)

// --- Register one, with a document ------------------------------------------------------------
const png = join(tmpdir(), 'e2e-gst.png')
writeFileSync(png, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64'))
await clickText(page, 'main button', 'Register a sub contractor')
await page.waitForSelector('#v-name')
await fill(page, '#v-name', 'M/s E2E Painters')
await fill(page, '#v-nature', 'Putty and painting works')
await fill(page, '#v-pan', 'SDFGHJK%^&*')
await fill(page, '#v-contact', 'Mr Rao')
await fill(page, '#v-phone', '9876543210')
await fill(page, '#v-address', '12 Main Road, Kokapet')
await fill(page, '#v-bank', 'State Bank of India')
await fill(page, '#v-account', '31831161699')
await fill(page, '#v-ifsc', 'SBIN0001234')
// the PAN card and the Aadhaar card must be attached before the form can be saved
await clickText(page, '[role=dialog] button', 'Save the form')
await waitForToast(page, 'PAN Card to be attached')
check('the form is not saved without the PAN card and the Aadhaar card attached', /Aadhar Card to be attached/.test(await page.$eval('[aria-live=polite]', (e) => e.textContent)))
await toastsGone(page)
await (await page.$('input[aria-label="Attach B) PAN Card"]')).uploadFile(png)
await (await page.$('input[aria-label="Attach C) Aadhar Card"]')).uploadFile(png)
await (await page.$('input[aria-label="Attach A) GST Certificate"]')).uploadFile(png)
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('e2e-gst.png'))
check('an attached document shows its file name and ticks its box', await page.$eval('[role=dialog]', (e) => e.textContent.includes('e2e-gst.png')) && (await page.$$eval('[role=dialog] input[type=checkbox]', (c) => c[0].checked)))
await clickText(page, '[role=dialog] button', 'Save the form')
await waitForToast(page, 'PAN')
check('a garbage PAN is refused at registration, in the server\'s words', /five letters/.test(await page.$eval('[aria-live=polite]', (e) => e.textContent)))
await toastsGone(page)
await fill(page, '#v-pan', 'ABCDE1234F')
await fill(page, '#v-bank', 'State Bank of India')
await fill(page, '#v-account', '31831161699')
await fill(page, '#v-ifsc', 'SBIN0001234')
await clickText(page, '[role=dialog] button', 'Save the form')
await waitForToast(page, 'added')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(500)
check('the new gang appears in the register', (await rows()) === before + 1)
const made = (await api(page, 'GET', '/api/wo/contractors?q=E2E')).data.contractors[0]
check('it was given the next vendor code and is registered (the owner signs as it is made)', !!made.vendor_code && made.registration_status === 'APPROVED', `${made.vendor_code} ${made.registration_status}`)
check('its document was stored against it', made.document_files.gst === 'e2e-gst.png' && made.documents.includes('gst'))
const file = await api(page, 'GET', `/api/wo/contractors/${made.id}/documents/gst`)
check('the stored document can be read back', file.status === 200)

// --- Open the form again ------------------------------------------------------------------------------
await fill(page, 'input[aria-label=Search]', 'E2E')
await sleep(700)
check('search narrows the register', (await rows()) === 1)
await clickText(page, 'table[aria-label=Vendors] tbody tr button', 'Form')
await page.waitForSelector('#v-name')
check('the form reopens with what was saved, and a link to the document', (await page.$eval('#v-name', (e) => e.value)) === 'M/s E2E Painters' && !!(await page.$('[role=dialog] a[href*="/documents/gst"]')))
await page.keyboard.press('Escape')

// --- Tabs ------------------------------------------------------------------------------------------------
await fill(page, 'input[aria-label=Search]', '')
await setValue(page, 'select[aria-label=Status]', 'Registered')
await sleep(600)
check('filtering to Registered lists only registered gangs', (await page.$$eval('table[aria-label=Vendors] tbody tr', (r) => r.every((x) => x.textContent.includes('Registered')))))

await done()
