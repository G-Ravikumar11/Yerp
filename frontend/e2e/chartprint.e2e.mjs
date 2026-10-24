import { writeFileSync } from 'node:fs'
import { api, clickText, launch, open, setValue, signIn } from './lib.mjs'

// Project Chart print: a text report built from the project's own data, with the company logo, ready for the browser's
// print dialog (and so for PDF). Print is stubbed to count the calls; the page is then rendered to PDF the way the dialog does.
const { page, check, done } = await launch()
await page.evaluateOnNewDocument(() => { if (window === window.top) window.__printed = 0; window.print = () => { window.top.__printed = (window.top.__printed || 0) + 1 } })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10)
await open(page, '/projects/chart')
const job = (await api(page, 'POST', '/api/jobs', { name: `Print site ${stamp}`, customer_name: 'Arabtec', site_address: 'Plot 12, Vanya City' })).data
const emp = (await api(page, 'POST', '/api/employees', { first_name: 'Print', last_name: `Eng${stamp}`, email: `print.${stamp}@example.in`, password: 'Passw0rd-QA1', phone: '', job_title: 'Engineer', department_id: null, reports_to: null, level: 'L1', role: 'employee', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })).data
const post = (b) => api(page, 'POST', `/api/jobs/${job.id}/schedule/activities`, b)
const a1 = (await post({ name: 'Excavation for raft', code: 'EX-1', planned_start: day(-40), planned_finish: day(-20), assigned_to_id: emp.id })).data.schedule.activities[0]
await api(page, 'POST', `/api/schedule/activities/${a1.id}/progress`, { percent: 60 })
const a2 = (await post({ name: 'Raft reinforcement and pour', code: 'RF-2', planned_start: day(-19), planned_finish: day(15), depends_on_id: a1.id, assigned_to_id: emp.id, notes: 'Cubes at 7 and 28 days' })).data.schedule.activities[1]
await post({ name: 'Plinth beams', code: 'PB-3', planned_start: day(16), planned_finish: day(40), depends_on_id: a2.id })
for (let i = 4; i <= 14; i++) await post({ name: `Superstructure bay ${i - 3}`, code: `SB-${i}`, planned_start: day(41 + i * 5), planned_finish: day(48 + i * 5) })
await post({ name: 'Structure complete', code: 'MS-1', planned_start: day(120), planned_finish: day(120), is_milestone: true })

await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForFunction((id) => document.querySelector(`#chart-job option[value="${id}"]`), { timeout: 90000 }, String(job.id))
await setValue(page, '#chart-job', String(job.id))
await page.waitForSelector('section[aria-label="Gantt chart"]', { timeout: 60000 })
const printBtn = () => clickText(page, 'main button', 'Print')

// no logo yet: it offers to add one
await printBtn()
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog]')].some((d) => /Add your company logo/.test(d.textContent)), { timeout: 8000 })
check('with no company logo, Print offers to add one', true)
check('nothing is printed until it is answered', (await page.evaluate(() => window.__printed)) === 0)
await clickText(page, '[role=dialog] button', 'Print without a logo')
await page.waitForFunction(() => window.__printed === 1, { timeout: 8000 })
check('"Print without a logo" opens the print dialog', true)
const report = () => page.$eval('#chart-print-root', (r) => ({ text: r.innerText, html: r.innerHTML }))
let r = await report()
check('the report is text: no image of the page, no canvas, no screenshot', !/<canvas/.test(r.html) && !/data:image\/(png|jpeg);base64,[A-Za-z0-9+/]{2000,}/.test(r.html))
check('the report prints from a document of its own, holding nothing of the app', await page.evaluate(() => { const d = document.getElementById('chart-print-frame')?.contentDocument; return !!d && d.body.children.length === 1 && d.body.firstElementChild.id === 'chart-print-root' && !d.querySelector('nav, aside, main, button') && d.title === 'Project Chart' }))
for (const want of ['Project Chart', `Print site ${stamp}`, 'Arabtec', 'Plot 12, Vanya City', 'Excavation for raft', 'Raft reinforcement and pour', `Print Eng${stamp}`, 'Cubes at 7 and 28 days', 'Structure complete', 'overdue', 'Prepared by'])
  check(`the report carries "${want}"`, r.text.includes(want))
const n = await page.$$eval('#chart-print-root tbody tr', (t) => t.length)
check('every activity has its own row', n === 15, String(n))
check('that document asks for A4 landscape with no browser margin, and the rows keep whole', await page.evaluate(() => { const d = document.getElementById('chart-print-frame').contentDocument; const c = [...d.querySelectorAll('style')].map((x) => x.textContent).join(''); return /@page \{ size: A4 landscape; margin: 0; \}/.test(c) && /table-header-group/.test(c) && /break-inside: avoid/.test(c) }))
await page.evaluate(() => document.getElementById('chart-print-frame')?.remove())

// a company logo: it heads the report, and the row of every page
await page.evaluate(async () => {
  const c = document.createElement('canvas'); c.width = 360; c.height = 110
  const x = c.getContext('2d'); x.fillStyle = '#0b3d91'; x.fillRect(0, 0, 360, 110); x.fillStyle = '#fff'; x.font = 'bold 44px Arial'; x.fillText('YALAVARTI', 22, 52); x.font = '24px Arial'; x.fillText('INFRA PROJECTS', 24, 88)
  await fetch('/api/client/logo', { method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ logo_url: c.toDataURL('image/png') }) })
})
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForFunction((id) => document.querySelector(`#chart-job option[value="${id}"]`), { timeout: 90000 }, String(job.id))
await setValue(page, '#chart-job', String(job.id))
await page.waitForSelector('section[aria-label="Gantt chart"]', { timeout: 60000 })
await printBtn()
await page.waitForFunction(() => window.__printed === 1, { timeout: 8000 })
r = await report()
check('with a logo, Print goes straight to the dialog', !(await page.evaluate(() => [...document.querySelectorAll('[role=dialog]')].some((d) => /company logo/.test(d.textContent)))))
check('the logo heads the report and repeats in the header of every page', (await page.$$eval('#chart-print-root img', (i) => i.length)) === 2 && (await page.$eval('#chart-print-root img.rp-logo', (i) => i.complete && i.naturalWidth > 0)))
// The print dialog is given the frame's document: open that same document on its own and print it as the dialog does.
const framed = async () => {
  const html = await page.evaluate(() => document.getElementById('chart-print-frame').contentDocument.documentElement.outerHTML)
  const p = await page.browser().newPage()
  await p.setContent('<!doctype html>' + html, { waitUntil: 'load' })
  return p
}
const toPdf = async (name) => {
  const p = await framed()
  const pdf = await p.pdf({ preferCSSPageSize: true, printBackground: true, displayHeaderFooter: false })
  await p.close()
  writeFileSync(process.env.PDF_OUT ? process.env.PDF_OUT.replace('.pdf', `-${name}.pdf`) : `chart-${name}.pdf`, pdf)
  const text = Buffer.from(pdf).toString('latin1')
  const box = text.match(/\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/)
  return { pages: (text.match(/\/Type\s*\/Page[^s]/g) ?? []).length, w: Number(box?.[1]), h: Number(box?.[2]), size: pdf.length }
}
const sheet = async () => {
  const p = await framed()
  await p.emulateMediaType('print')
  const r = await p.evaluate(() => { const r = document.querySelector('#chart-print-root .rp-sheet').getBoundingClientRect(); const pg = document.querySelector('#chart-print-root .rp-page'); return { mmH: r.height * 25.4 / 96, mmW: r.width * 25.4 / 96, zoom: pg.style.zoom, multi: pg.classList.contains('multi'), compact: pg.classList.contains('compact'), overflow: [...pg.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().right > pg.getBoundingClientRect().right + 1).map((e) => e.tagName + '.' + e.className).slice(0, 4) } })
  await p.close()
  return r
}
const reprint = async () => {
  await page.evaluate(() => { document.getElementById('chart-print-frame')?.remove(); window.__printed = 0 })
  await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
  await page.reload({ waitUntil: 'networkidle0' })
  await page.waitForFunction((id) => document.querySelector(`#chart-job option[value="${id}"]`), { timeout: 90000 }, String(job.id))
  await setValue(page, '#chart-job', String(job.id))
  await page.waitForSelector('section[aria-label="Gantt chart"]', { timeout: 60000 })
  await printBtn()
  await page.waitForFunction(() => window.__printed === 1, { timeout: 8000 })
}
let sh = await sheet()
let pdf = await toPdf('small')
check('the PDF is A4 landscape (842 x 595 points), not Letter', Math.abs(pdf.w - 841.89) < 2 && Math.abs(pdf.h - 595.28) < 2, `${pdf.w} x ${pdf.h}`)
check('this project prints on exactly one page', pdf.pages === 1, `${pdf.pages} pages, ${pdf.size} bytes`)
check('the report sits inside the sheet: 297 mm wide, no taller than 210 mm, nothing cut off sideways', Math.abs(sh.mmW - 297) < 1 && sh.mmH <= 210.5 && !sh.overflow.length && !sh.multi, JSON.stringify(sh))

// a longer programme is still one page, tighter and scaled
for (let i = 0; i < 25; i++) await post({ name: `Finishing block ${i + 1}`, code: `FB-${i + 1}`, planned_start: day(150 + i * 3), planned_finish: day(156 + i * 3) })
await reprint()
sh = await sheet()
pdf = await toPdf('long')
check('40 activities still print on exactly one A4 landscape page', pdf.pages === 1 && Math.abs(pdf.w - 841.89) < 2, `${pdf.pages} pages, zoom ${sh.zoom}`)
check('by tightening the rows and scaling, not by cutting any off', (await page.$$eval('#chart-print-root tbody tr', (t) => t.length)) === 40 && sh.compact && !sh.overflow.length && Number(sh.zoom) >= 0.55 && sh.mmH <= 210.5, JSON.stringify(sh))

// far too many to read on one sheet: it keeps the writing legible and runs to more pages, header repeated
for (let i = 0; i < 70; i++) await post({ name: `Snag item ${i + 1}`, code: `SN-${i + 1}`, planned_start: day(240 + i), planned_finish: day(243 + i) })
await reprint()
sh = await sheet()
pdf = await toPdf('huge')
check('110 activities do not shrink beyond reading: they run to more pages with the header repeated', pdf.pages >= 2 && sh.multi && Number(sh.zoom) >= 0.55, `${pdf.pages} pages, zoom ${sh.zoom}`)
await page.evaluate(() => document.getElementById('chart-print-frame')?.remove())
check('and the screen itself was never changed for printing', !(await page.evaluate(() => document.body.classList.contains('printing-chart'))) && !!(await page.$('section[aria-label="Gantt chart"]')))
await done()
