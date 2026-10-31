import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// What Equipment & Plant checks for itself, through the screens: the meter, gaps and a replaced meter in the logbook, fuel
// flags, a hire bill against its agreement, alerts, and plant cost on the project - each checked against the server.
const { page, check, done } = await launch({ allow: [/400 POST \/api\/plant\/logs/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const tab = async (label) => { await clickText(page, '[role=tab]', label); await sleep(900) }
const pick = (sel, re) => page.$eval(sel, (s, re) => [...s.options].find((o) => new RegExp(re).test(o.textContent))?.value, re).then((v) => setValue(page, sel, v))
const confirm = async (reason, label) => {
  await page.waitForSelector('#confirm-reason')
  await fill(page, '#confirm-reason', reason)
  await clickText(page, '[role=dialog] button', label)
  await page.waitForFunction(() => !document.querySelector('#confirm-reason'), { timeout: 10000 })
  await sleep(800)
}

await open(page, '/projects/equipment')
const job = (await api(page, 'POST', '/api/jobs', { name: `Check site ${stamp}`, customer_name: 'E2E' })).data
const m = (await api(page, 'POST', '/api/assets', { name: `Excavator ${stamp}`, category: 'Earthmoving', meter_reading: 0 })).data
await api(page, 'POST', `/api/assets/${m.id}/move`, { to_job_id: job.id })
const made = await api(page, 'POST', '/api/employees', { first_name: 'Sita', last_name: `Op${stamp}`, email: `sita.${stamp}@yprojects.co.in`, phone: '9876512345', gender: 'Female', emergency_contact: 'Ravi', emergency_phone: '9876500000', salary: 20800 })
if (made.status !== 200) throw new Error('employee: ' + JSON.stringify(made.data))
const e = made.data
const shift = { asset_id: m.id, employee_id: e.id, shift: 'Day', start_time: '07:00', end_time: '19:00', break_minutes: 60 }
await api(page, 'POST', '/api/plant/logs', { ...shift, log_date: day(-8), opening_meter: 100, closing_meter: 108 })
await api(page, 'POST', '/api/plant/logs', { ...shift, log_date: day(-4), opening_meter: 120, closing_meter: 128 })

// the machine form keeps the two new settings
await open(page, '/projects/equipment?tab=register')
await page.waitForSelector('table[aria-label=Machines] tbody tr')
check('the register has no Log day button', !/Log day/.test(await text('table[aria-label=Machines]')))
await page.evaluate((n) => [...[...document.querySelectorAll('table[aria-label=Machines] tbody tr')].find((r) => r.textContent.includes(n)).querySelectorAll('button')].find((b) => b.textContent.trim() === 'Edit').click(), m.name)
await page.waitForSelector('#mc-norm')
await fill(page, '#mc-norm', '10')
await fill(page, '#mc-tank', '200')
await clickText(page, '[role=dialog] button', 'Save')
await page.waitForFunction(() => !document.querySelector('#mc-norm'), { timeout: 10000 })
const saved = (await api(page, 'GET', `/api/assets/${m.id}`)).data
check('fuel norm and tank capacity are saved from the form', saved.fuel_norm_lph === 10 && saved.tank_capacity_l === 200, JSON.stringify([saved.fuel_norm_lph, saved.tank_capacity_l]))
await toastsGone(page).catch(() => {})

// the logbook: a gap, a lower reading refused, and a replaced meter
await tab('Logbook')
await page.waitForSelector('[aria-label="Meter gaps"]')
check('the gap in the readings is flagged with its days', /3 days without a reading/.test(await text('[aria-label="Meter gaps"]')), await text('[aria-label="Meter gaps"]'))
await clickText(page, '[aria-label="Meter gaps"] button', 'Review')
await confirm('Stood at the yard for a week', 'Save')
check('the gap is explained and says who by', /Stood at the yard/.test(await text('[aria-label="Meter gaps"]')))

await clickText(page, 'main button', 'Log a shift')
await page.waitForSelector('#lb-m')
await page.waitForFunction((c) => [...document.querySelectorAll('#lb-m option')].some((o) => o.textContent.includes(c)), { timeout: 15000 }, m.code)
await pick('#lb-m', m.code)
await page.waitForFunction(() => [...document.querySelectorAll('#lb-e option')].some((o) => /Sita/.test(o.textContent)), { timeout: 15000 })
await pick('#lb-e', `Sita Op${stamp}`)
await setValue(page, '#lb-d', day(-3))
await setValue(page, '#lb-st', '07:00')
await setValue(page, '#lb-et', '19:00')
await fill(page, '#lb-om', '5')
await fill(page, '#lb-cm', '13')
await sleep(300)
check('a low opening reading is warned of as it is typed', /only runs forward/.test(await text('[role=dialog]')))
await clickText(page, '[role=dialog] button', 'Log the shift')
await sleep(1200)
check('the server refuses it and says why', /Meter Replaced/.test(await text('[role=dialog]')) && /128/.test(await text('[role=dialog]')), await text('[role=dialog]'))
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] label')].find((l) => l.textContent.includes('Meter Replaced')).querySelector('input').click())
await page.waitForSelector('#lb-rr')
await setValue(page, '#lb-rd', day(-3))
await fill(page, '#lb-rr', 'Cluster failed')
await clickText(page, '[role=dialog] button', 'Log the shift')
await waitForToast(page, 'Logged')
await toastsGone(page).catch(() => {})
const history = (await api(page, 'GET', `/api/plant/machines/${m.id}/meter-history`)).data.history
check('the replacement is on the record, old and new', history.some((h) => h.type === 'Meter replaced' && h.opening === 128 && h.closing === 5))

// the fuel screen
await api(page, 'POST', '/api/plant/fuel', { asset_id: m.id, filled_on: day(-4), litres: 40, rate: 90 })
await api(page, 'POST', '/api/plant/fuel', { asset_id: m.id, filled_on: day(-3), litres: 250, rate: 90 })
await open(page, '/projects/equipment?tab=fuel')
await page.waitForSelector('table[aria-label="Fuel flags"] tbody tr')
const flags = await text('table[aria-label="Fuel flags"]')
check('fuel flags show the fill and the reason, and do not say theft', /Requires Investigation/.test(flags) && /Fuel Anomaly/.test(flags) && !/theft/i.test(flags), flags)
check('fuel by machine shows the norm and the tank', /10/.test(await text('table[aria-label="Fuel by machine"]')) && /200/.test(await text('table[aria-label="Fuel by machine"]')))
await clickText(page, 'table[aria-label="Fuel flags"] button', 'Dismiss')
await confirm('Two machines on one voucher', 'Save')
check('a flag is dismissed with its reason, and stays listed', /Dismissed/.test(await text('table[aria-label="Fuel flags"]')) && /Two machines on one voucher/.test(await text('table[aria-label="Fuel flags"]')))

// a hire bill against its agreement
const crane = (await api(page, 'POST', '/api/assets', { name: `Crane ${stamp}`, category: 'Lifting', ownership: 'Rented', hire_rate: 1, hire_basis: 'Day' })).data
await api(page, 'POST', `/api/assets/${crane.id}/move`, { to_job_id: job.id })
const prov = (await api(page, 'POST', '/api/plant/rental-providers', { name: `Sai ${stamp}` })).data.provider
const month = day(-40).slice(0, 7)
const rental = (await api(page, 'POST', '/api/plant/rentals', { asset_id: crane.id, provider_id: prov.id, agreement_no: `AG-${stamp}`, start_date: `${month}-01`, expected_return: day(30), rate: 90000, billing: 'Monthly' })).data
await api(page, 'POST', `/api/plant/rentals/${rental.id}/invoices`, { invoice_no: `INV-${stamp}`, invoice_date: `${month}-28`, period_from: `${month}-01`, period_to: `${month}-28`, amount: 500000 })
await open(page, '/projects/equipment?tab=rentals')
await page.waitForSelector('table[aria-label="Rental bills"] tbody tr')
const bills = await text('table[aria-label="Rental bills"]')
check('the bill sits beside the agreement and is flagged', /Mismatch/.test(bills) && /5,00,000/.test(bills), bills.slice(0, 200))
await clickText(page, 'table[aria-label="Rental bills"] button', 'Dispute')
await confirm('Rate is 90,000', 'Dispute')
check('finance disputes it, and the billed amount stands', /Disputed by/.test(await text('table[aria-label="Rental bills"]')) && /5,00,000/.test(await text('table[aria-label="Rental bills"]')))

// an emergency, at once
await api(page, 'POST', '/api/plant/maintenance', { asset_id: m.id, kind: 'Emergency', priority: 'Urgent', description: 'Boom cracked', out_of_service: true })
await open(page, '/projects/equipment?tab=alerts')
await page.waitForSelector('table[aria-label="Plant alerts"] tbody tr')
check('the emergency is on the alerts screen with what is needed', new RegExp(m.code).test(await text('table[aria-label="Plant alerts"]')) && /Urgent/.test(await text('table[aria-label="Plant alerts"]')) && /Delivered/.test(await text('table[aria-label="Plant alerts"]')))
await clickText(page, 'table[aria-label="Plant alerts"] button', 'Resolved')
await page.waitForSelector('#confirm-reason')
await fill(page, '#confirm-reason', 'Boom welded')
await clickText(page, '[role=dialog] button', 'Save')
await sleep(1200)
check('the alert is closed with who and why', /Boom welded/.test(await text('table[aria-label="Plant alerts"]')))
await clickText(page, 'main button', 'Alert settings')
await page.waitForSelector('#as-document_alert_days')
check('alert settings open with their values', Number(await page.$eval('#as-document_alert_days', (x) => x.value)) === 30)
await page.keyboard.press('Escape')
await sleep(300)

// the machine's own page
await open(page, '/projects/equipment?tab=register')
await page.waitForSelector('table[aria-label=Machines] tbody tr')
await clickText(page, 'table[aria-label=Machines] tbody button', m.name)
await page.waitForSelector('table[aria-label="Meter history"] tbody tr')
const detail = await text('main')
check('the machine shows its norm, tank, breakdowns and meter history', /10 L\/h/.test(detail) && /200 L/.test(detail) && /Boom cracked/.test(detail) && /Meter replaced/.test(detail))

// the project
const pnl = (await api(page, 'GET', `/api/jobs/${job.id}/pnl`)).data.cost
check('the project carries fuel and the bill once', pnl.equipment_breakdown.fuel === 26100 && pnl.equipment_breakdown.rental === 500000 && pnl.equipment === 526100, JSON.stringify(pnl.equipment_breakdown))
await open(page, '/projects/profit')
await page.waitForSelector('table[aria-label="Plant cost by project"] tbody tr')
await page.evaluate((n) => [...document.querySelectorAll('table[aria-label="Plant cost by project"] button')].find((b) => b.textContent.includes(n)).click(), `Check site ${stamp}`)
await page.waitForSelector('table[aria-label="Plant cost lines"] tbody tr')
const lines = await text('table[aria-label="Plant cost lines"]')
check('each line says where it came from', /Fuel register/.test(lines) && /Rental invoice/.test(lines) && new RegExp(`INV-${stamp}`).test(lines), lines.slice(0, 160))
await page.keyboard.press('Escape')

// small screens
await page.setViewport({ width: 390, height: 800 })
for (const t of ['alerts', 'fuel', 'rentals']) {
  await open(page, `/projects/equipment?tab=${t}`)
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check(`the ${t} tab does not run off a phone`, over <= 1, String(over))
}
await done()
