import { api, clickText, fill, launch, open, setValue, sleep, signIn, toastsGone, waitForToast } from './lib.mjs'

// Staff: a member of staff signs in to the new interface and finds their own work, in the department the owner gave them.
const { page, check, done } = await launch({ allow: [/\/api\/employees|\/api\/hr|\/api\/approvals|403 /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const dept = `QA Survey ${stamp}`
const email = `qa.staff.${stamp}@example.in`
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const body = () => page.$eval('body', (e) => e.textContent.replace(/\s+/g, ' '))

// The owner sets up the department and the person, from the new interface's own API
const d = await api(page, 'POST', '/api/departments', { name: dept, description: 'Surveying', color: '#0f766e', icon: 'compass' })
const made = await api(page, 'POST', '/api/employees', { first_name: 'Ravi', last_name: `Survey${stamp}`, email, password: 'Passw0rd-QA1', phone: '', job_title: 'Surveyor', department_id: d.data.id, reports_to: null, level: 'L1', role: 'employee', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 30000, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
check('the owner has created the department and the employee', d.status === 200 && made.status === 200, JSON.stringify([d.status, made.status, made.data]).slice(0, 200))

// HR sets the new starter a goal, and a document to provide
await api(page, 'POST', `/api/employees/${made.data.id}/goals`, { title: `Survey 10 sites ${stamp}`, description: 'Before the month ends', target_value: 10, current_value: 2, unit: 'sites', category: 'performance', priority: 'high', due_date: '2026-12-31' })
// The owner has the app open on this device; then somebody else signs in here. What was kept for the owner must not be theirs to see.
await open(page, '/')
let asked = 0
page.on('request', (r) => { if (r.url().includes('/api/')) asked++ })
// Sign out the owner; sign in as the member of staff
await api(page, 'POST', '/api/client/logout')
const login = await api(page, 'POST', '/api/employee/auth/login', { email, password: 'Passw0rd-QA1' })
check('the member of staff signs in', login.status === 200, JSON.stringify(login.data).slice(0, 120))

await open(page, '/')
await page.waitForFunction(() => document.querySelector('main h1')?.textContent.includes('Good'), { timeout: 15000 })
check("the front page is the person's own day, not the owner's Command Center", (await text('main h1')).startsWith('Good') && (await text('main h1')).includes('Ravi'), await text('main h1'))
check("the department the owner chose is on the page and in the top bar", (await text('main')).includes(dept) && (await text('header')).includes(dept), await text('header'))

const menu = await text('nav[aria-label="Main"], aside')
check('switching person in the same browser settles at once (no request storm)', asked < 40, String(asked) + ' requests')
check('the menu holds their own work', ['Overview', 'Timesheet', 'My Costs', 'My Leave', 'Payslips', 'Documents'].every((w) => menu.includes(w)), menu.slice(0, 200))
check('and leaves out what they have no right to (Money, People, Command Center)', !/Money|Payments|Employees|Command Center|Settings/.test(menu), menu.slice(0, 300))

// The clock: signing in clocked them in already; they take a break, come back, and clock out
await page.waitForFunction(() => document.querySelector('section[aria-label=Clock]')?.textContent.match(/In since|Not clocked|Not a working/), { timeout: 10000 })
const clocked = (await text('section[aria-label=Clock]')).includes('In since')
if (clocked) {
  check('they are already clocked in from signing in', true, await text('section[aria-label=Clock]'))
  await clickText(page, 'main button', 'Take a break')
  await waitForToast(page, 'Break started')
  await page.waitForFunction(() => document.querySelector('section[aria-label=Clock]')?.textContent.includes('On a break'), { timeout: 10000 })
  check('a break shows on the clock', true)
  await toastsGone(page)
  await clickText(page, 'main button', 'End break')
  await waitForToast(page, 'Break ended')
  await page.waitForFunction(() => document.querySelector('section[aria-label=Clock]')?.textContent.includes('Take a break'), { timeout: 10000 })
  await toastsGone(page)
  await clickText(page, 'main button', 'Clock out')
  await waitForToast(page, 'Clocked out')
  await page.waitForFunction(() => document.querySelector('section[aria-label=Clock]')?.textContent.includes('Done for the day'), { timeout: 10000 })
  check('clocking out ends the day', (await text('section[aria-label=Clock]')).includes('to'), await text('section[aria-label=Clock]'))
  await toastsGone(page)
  await open(page, '/me/timesheet')
  await page.waitForSelector('table[aria-label=Timesheet] tbody tr')
  check('the timesheet has today', (await text('table[aria-label=Timesheet] tbody')).includes(String(new Date().getFullYear())), await text('table[aria-label=Timesheet] tbody'))
} else {
  check('(not a working day: the clock waits)', await page.evaluate(() => !!document.querySelector('section[aria-label=Clock]')))
}

// Leave
await open(page, '/me/leave')
await page.waitForSelector('main h1')
check('leave shows the balance', (await text('main')).includes('Annual leave left'), (await text('main')).slice(0, 120))
await clickText(page, 'button', 'Ask for leave')
await page.waitForSelector('#lv-from')
const day = new Date(Date.now() + 21 * 86400000)
while ([0, 6].includes(day.getDay())) day.setDate(day.getDate() + 1)
const iso = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
await setValue(page, '#lv-from', iso)
await setValue(page, '#lv-to', iso)
await fill(page, '#lv-reason', 'Family function')
await clickText(page, '[role=dialog] button', 'Send request')
await waitForToast(page, 'submitted')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(400)
check('the request is listed as waiting', (await text('table[aria-label="Leave requests"] tbody')).includes('Pending'), await text('table[aria-label="Leave requests"] tbody'))
await toastsGone(page)

// Costs
await open(page, '/me/costs')
await page.waitForSelector('main h1')
await clickText(page, 'button', 'Raise a cost')
await page.waitForSelector('#co-vendor')
await fill(page, '#co-vendor', `Sharma Hardware ${stamp}`)
await fill(page, '#co-amount', '1000')
await fill(page, '#co-tax', '180')
await fill(page, '#co-ref', `INV-${stamp}`)
check('the total is worked out as they type', (await text('[role=dialog]')).includes('1,180'), (await text('[role=dialog]')).slice(-140))
await clickText(page, '[role=dialog] button', 'Send for approval')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'), { timeout: 10000 })
await sleep(500)
const cost = await text('table[aria-label="My costs"] tbody')
check('the cost is listed with its state', cost.includes(`Sharma Hardware ${stamp}`) && /With approver|Not sent|Approved/.test(cost), cost)
await toastsGone(page)

// Orders (the Purchase Orders screen in staff mode), Payslips, Documents
await open(page, '/me/orders')
check('My Orders opens for them', (await text('main h1')).includes('My Orders'), await text('main h1'))
await open(page, '/me/payslips')
check('Payslips opens (none yet)', (await text('main')).includes('No payslips yet'))
await open(page, '/me/documents')
check('Documents opens', (await text('main h1')).includes('Documents'))


// The rest of the portal: goals, notifications, team, profile, onboarding, and the overview's week
await open(page, '/')
await page.waitForSelector('section[aria-label="This week"] [role=img]')
check('the overview shows the week, recent attendance and the team', !!(await page.$('section[aria-label="Recent attendance"]')) && !!(await page.$('section[aria-label="Team presence"]')))
await page.waitForSelector('button[aria-label^="Notifications"]')
check('the bell says there is something new (the goal HR set)', /unread/.test(await page.$eval('button[aria-label^="Notifications"]', (e) => e.getAttribute('aria-label'))), await page.$eval('button[aria-label^="Notifications"]', (e) => e.getAttribute('aria-label')))
await page.click('button[aria-label^="Notifications"]')
await page.waitForSelector('[role=dialog][aria-label=Notifications] li')
check('and lists it', (await text('[role=dialog][aria-label=Notifications]')).includes('oal'))
await clickText(page, '[role=dialog][aria-label=Notifications] button', 'Mark all read')
await page.waitForFunction(() => !/unread/.test(document.querySelector('button[aria-label^="Notifications"]').getAttribute('aria-label')), { timeout: 8000 })
check('marking all read clears the count', true)
await page.keyboard.press('Escape')

await open(page, '/me/goals')
await page.waitForSelector(`section[aria-label="Survey 10 sites ${stamp}"]`)
check('the goal is there with its progress', (await text(`section[aria-label="Survey 10 sites ${stamp}"]`)).includes('20%'))
await clickText(page, 'main button', 'Update progress')
await page.waitForSelector('#pm-v')
await fill(page, '#pm-v', '5')
await clickText(page, '[role=dialog] button', 'Save progress')
await waitForToast(page, 'Progress updated')
await sleep(600)
check('updating it moves the bar', (await text(`section[aria-label="Survey 10 sites ${stamp}"]`)).includes('50%'))
await toastsGone(page)

await open(page, '/me/team')
await page.waitForSelector('main section')
check('My Team lists the department, with who is in', (await text('main')).includes('Ravi') && /Working|Away|On a break/.test(await text('main')))
await open(page, '/me/profile')
await page.waitForSelector('section[aria-label=Profile]')
check('My Profile shows the department the owner chose, and the goal count', (await text('section[aria-label=Profile]')).includes(dept) && /1 goal/.test(await text('section[aria-label=Profile]')), (await text('section[aria-label=Profile]')).slice(0, 160))
await open(page, '/me/onboarding')
check('Onboarding opens with its progress', (await text('main')).includes('Onboarding progress'))
// What the owner sees still works for the owner
await api(page, 'POST', '/api/employee/auth/logout')
await signIn(page)
await open(page, '/')
await page.waitForFunction(() => document.querySelector('main h1')?.textContent.includes('Command') || document.querySelectorAll('figure svg').length >= 1, { timeout: 15000 })
const ownerMenu = await text('aside')
check('signed in as the owner again, the menu is the owner menu (Command Center, no My work)', ownerMenu.includes('Command Center') && !ownerMenu.includes('My work'), ownerMenu.slice(0, 120))
await done()
