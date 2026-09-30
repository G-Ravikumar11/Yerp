import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Site diary: the owner records a day with labour and plant, signs it off and adds a photo; a member of staff can record but not sign off.
const { page, check, done } = await launch()
await signIn(page)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const dayIso = (n) => { const d = new Date(Date.now() - n * 86400000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

await open(page, '/projects/diary')
await page.waitForFunction(() => document.querySelector('#diary-job option[value]')?.value, { timeout: 10000 })
await clickText(page, 'main button', 'Record a day')
await page.waitForSelector('#dy-date')
const when = dayIso(40 + (Date.now() % 20000))
await setValue(page, '#dy-date', when)
await setValue(page, '#dy-weather', 'Rain')
await fill(page, '#dy-rain', '5')
await fill(page, '#dy-work', 'Raft reinforcement, block A')
await fill(page, '#dy-hold', 'Rain after lunch')
await fill(page, '[aria-label="Headcount 1"]', '5')
await fill(page, '[aria-label="Hours 1"]', '8')
await fill(page, '[aria-label="Rate 1"]', '600')
await fill(page, '[aria-label="Plant 1"]', 'JCB 3DX')
await fill(page, '[aria-label="Worked 1"]', '6')
await fill(page, '[aria-label="Plant rate 1"]', '1000')
await sleep(200)
const totals = await text('[aria-label=Totals]')
check('the day cost is worked out as it is typed (5 mandays, labour 3,000, plant 6,000)', totals.includes('5 mandays') && totals.includes('3,000') && totals.includes('6,000') && totals.includes('9,000'), totals)
const png = join(tmpdir(), 'site.png')
writeFileSync(png, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64'))
const input = await page.$('input[aria-label="Photos of the day"]')
await input.uploadFile(png)
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('site.png'))
check('a photo chosen for the day is shown', true)
await clickText(page, '[role=dialog] button', 'Save the day')
await waitForToast(page, 'Diary opened')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(600)
const row = () => page.evaluate(() => document.querySelector('table[aria-label="Diary days"] tbody')?.textContent.replace(/\s+/g, ' '))
check('the day is listed, rained off, with its mandays', /rained off/.test(await row()) && /Raft reinforcement/.test(await row()) && /Draft/.test(await row()), await row())
await toastsGone(page)

// Photos kept against the day
await clickText(page, 'table[aria-label="Diary days"] tbody button', 'Photos')
await page.waitForSelector('[role=dialog] figure', { timeout: 8000 })
check('the photo went up with the day', (await text('[role=dialog]')).includes('site'))
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))

// Sign off
await clickText(page, 'table[aria-label="Diary days"] tbody button', dayIsoLabel(when))
await page.waitForSelector('#dy-work')
await clickText(page, '[role=dialog] button', 'Save and sign off')
await waitForToast(page, 'signed')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(600)
check('signing off locks it', /Signed off/.test(await row()), await row())
await toastsGone(page)
await clickText(page, 'table[aria-label="Diary days"] tbody button', dayIsoLabel(when))
await page.waitForSelector('#dy-work')
check('a signed-off day cannot be rewritten', await page.$eval('#dy-work', (e) => e.matches(':disabled')) && (await text('[role=dialog]')).includes('Signed off on'))
await page.keyboard.press('Escape')

function dayIsoLabel(iso) {
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${iso.slice(8)} ${m[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}`
}

// --- A member of staff on site ---------------------------------------------------------------
const stamp = Date.now().toString().slice(-6)
const email = `qa.site.${stamp}@example.in`
const made = await api(page, 'POST', '/api/employees', { first_name: 'Kiran', last_name: `Site${stamp}`, email, password: 'Passw0rd-QA1', phone: '', job_title: 'Supervisor', department_id: null, reports_to: null, level: 'L1', role: 'employee', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 20000, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
await api(page, 'POST', '/api/client/logout')
await api(page, 'POST', '/api/employee/auth/login', { email, password: 'Passw0rd-QA1' })
await open(page, '/projects/diary')
await page.waitForFunction(() => document.querySelector('#diary-job option[value]')?.value, { timeout: 10000 })
check('staff see the sites they work on in the picker', (await page.$$eval('#diary-job option[value]', (o) => o.length)) > 0)
await clickText(page, 'main button', 'Record a day')
await page.waitForSelector('#dy-date')
await setValue(page, '#dy-date', dayIso(20100 + (Date.now() % 5000)))
await fill(page, '#dy-work', 'Levelling')
await clickText(page, '[role=dialog] button', 'Save the day')
await waitForToast(page, 'Diary opened')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(500)
check('staff can record a day', /Levelling/.test(await row()), await row())
await toastsGone(page)
await page.evaluate(() => [...document.querySelectorAll('table[aria-label="Diary days"] tbody tr')].find((r) => r.textContent.includes('Levelling')).querySelectorAll('button')[1].click())
await page.waitForSelector('[role=dialog] input[aria-label="Take a photo"]')
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await page.evaluate(() => [...document.querySelectorAll('table[aria-label="Diary days"] tbody tr')].find((r) => r.textContent.includes('Levelling')).querySelector('button').click())
await page.waitForSelector('#dy-work')
check('but a plain member of staff cannot sign it off', !(await text('[role=dialog]')).includes('Save and sign off'))
await done()
