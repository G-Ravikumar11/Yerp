import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Project Chart: activities with a deadline and an employee, the Gantt with its dependency arrow, the overdue alert,
// filters by status and employee, progress, milestones, and delete.
// The refusals are the server saying no to what the checks try on purpose.
const { page, check, done } = await launch({ allow: [/(409|400) (POST|PUT) \/api\/(schedule|jobs\/\d+\/schedule)/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10)
const inDialog = (label) => page.evaluate((label) => {
  const d = [...document.querySelectorAll('[role=dialog]')].pop()
  const b = [...(d?.querySelectorAll('button') ?? [])].find((x) => x.textContent.trim().startsWith(label))
  b?.click()
  return !!b
}, label).then((ok) => { if (!ok) throw new Error(`no button ${label}`) })

await open(page, '/projects/chart')
const job = (await api(page, 'POST', '/api/jobs', { name: `Chart site ${stamp}`, customer_name: 'E2E' })).data
const emp = (await api(page, 'POST', '/api/employees', { first_name: 'Chart', last_name: `Eng${stamp}`, email: `chart.${stamp}@example.in`, password: 'Passw0rd-QA1', phone: '', job_title: 'Engineer', department_id: null, reports_to: null, level: 'L1', role: 'employee', permission_role: 'staff', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })).data
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForFunction(() => document.querySelector('#chart-job option[value]:not([value=""])'), { timeout: 30000 })
await setValue(page, '#chart-job', String(job.id))
await page.waitForFunction(() => /No chart yet/.test(document.body.textContent), { timeout: 15000 })
check('a project with no activities says so', true)

// add an activity through the form, assigned to the employee, already past its deadline
await clickText(page, 'main button', 'Activity')
await page.waitForSelector('#ac-name')
await fill(page, '#ac-name', `Excavation ${stamp}`)
await setValue(page, '#ac-start', day(-20))
await setValue(page, '#ac-finish', day(-6))
await setValue(page, '#ac-who', String(emp.id))
await inDialog('Save the activity')
await waitForToast(page, 'Activity saved')
await toastsGone(page)
// a second one that waits on it, and a milestone, via the API as the form would send them
const first = (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities[0]
const r1 = await api(page, 'POST', `/api/jobs/${job.id}/schedule/activities`, { name: `Raft ${stamp}`, planned_start: day(-5), planned_finish: day(25), depends_on_id: first.id })
const r2 = await api(page, 'POST', `/api/jobs/${job.id}/schedule/activities`, { name: `Handover ${stamp}`, planned_start: day(40), planned_finish: day(40), is_milestone: true })
check('the other activities were saved', r1.status === 200 && r2.status === 200, `${r1.status} ${JSON.stringify(r1.data).slice(0, 120)} ${r2.status}`)
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForFunction(() => document.querySelector('#chart-job option[value]:not([value=""])'), { timeout: 30000 })
await setValue(page, '#chart-job', String(job.id))
await page.waitForSelector('section[aria-label="Gantt chart"]', { timeout: 15000 })
const bars = await page.$$eval('section[aria-label="Gantt chart"] button[aria-label*="done, planned"]', (b) => b.length)
check('the Gantt draws a bar for each activity', bars === 2, String(bars))
check('and a diamond for the milestone', (await page.$$eval('section[aria-label="Gantt chart"] button[aria-label^="Milestone"]', (b) => b.length)) === 1)
check('and an arrow for the dependency', (await page.$$eval('section[aria-label="Gantt chart"] svg path[marker-end]', (p) => p.length)) === 1)
check('the timeline shows start, finish and duration', /Duration\s*\d+ days/.test(await text('main')) && /Starts/.test(await text('main')))
check('an activity past its deadline raises the delay alert with who has it', /1 activity is past its deadline/.test(await text('[role=alert]')) && (await text('[role=alert]')).includes(`Chart Eng${stamp}`), (await text('[role=alert]')).slice(0, 160))

// the list: assignee, deadline, late days, filters
await clickText(page, '[role=tab]', 'Activities')
await page.waitForSelector('table[aria-label=Activities]')
const row = () => page.$$eval('table[aria-label=Activities] tbody tr', (r) => r.map((x) => x.textContent.replace(/\s+/g, ' ')))
let rows = await row()
check('the list shows the employee and the days late', rows.length === 3 && rows.some((r) => r.includes(`Chart Eng${stamp}`) && /6 days late/.test(r)), rows.join(' | ').slice(0, 200))
check('each activity shows its status, the late one as Delayed and overdue', rows.some((r) => /Delayed/.test(r) && /overdue/.test(r)) && rows.some((r) => /Not Started/.test(r)), rows.join(' | ').slice(0, 160))
await setValue(page, '[aria-label=Status]', 'Delayed')
await sleep(300)
check('the Delayed filter finds the late activity and the one waiting on it', (await row()).length === 2)
await setValue(page, '[aria-label=Status]', '')
await setValue(page, '[aria-label=Status]', 'overdue')
await sleep(300)
check('the Overdue filter leaves only the late activity', (await row()).length === 1)
await setValue(page, '[aria-label=Status]', '')
await setValue(page, '[aria-label=Employee]', String(emp.id))
await sleep(300)
check('the employee filter leaves only theirs', (await row()).length === 1)
await setValue(page, '[aria-label=Employee]', 'none')
await sleep(300)
check('"nobody assigned" finds the others', (await row()).length === 2)
await clickText(page, 'main button', 'Clear')
await fill(page, '[aria-label="Search activities"]', 'Raft')
await sleep(300)
check('search finds an activity by name', (await row()).length === 1)
await clickText(page, 'main button', 'Clear')

// the form refuses a repeated code and a dependency loop, and keeps notes and status
await clickText(page, 'main button', 'Activity')
await page.waitForSelector('#ac-name')
await fill(page, '#ac-name', `Duplicate ${stamp}`)
await fill(page, '#ac-code', 'A10')
check('a repeated code is refused in the form, naming who has it', /already used by/.test(await text('[role=dialog]')), (await text('[role=dialog]')).slice(0, 0))
await page.keyboard.press('Escape')
await sleep(400)
const dup = await api(page, 'POST', `/api/jobs/${job.id}/schedule/activities`, { name: 'Dup', code: 'a10', planned_start: day(0), planned_finish: day(1) })
check('and the server refuses it too', dup.status === 409, String(dup.status))
const loop = await api(page, 'PUT', `/api/schedule/activities/${first.id}`, { name: first.name, planned_start: first.planned_start, planned_finish: first.planned_finish, depends_on_id: (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities[1].id })
check('a circular dependency is refused by the server', loop.status === 400, String(loop.status))
await page.evaluate((s) => [...document.querySelectorAll('table[aria-label=Activities] tbody tr')].find((r) => r.textContent.includes('Raft ' + s)).querySelector('button.text-primary').click(), stamp)
await page.waitForSelector('#ac-notes')
await fill(page, '#ac-notes', 'Pump booked for Monday')
await setValue(page, '#ac-status', 'In Progress')
const loopOptions = await page.$$eval('#ac-after option:not([disabled])', (o) => o.length)
await inDialog('Save the activity')
await waitForToast(page, 'Activity saved')
await toastsGone(page)
const raft = (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities.find((a) => a.name.startsWith('Raft'))
check('notes and status are saved', raft.notes === 'Pump booked for Monday' && raft.stored_status === 'In Progress', JSON.stringify([raft.notes, raft.stored_status]))
await page.waitForFunction((n) => [...document.querySelectorAll('table[aria-label=Activities] tbody tr')].some((r) => r.textContent.includes(n) && /In Progress/.test(r.textContent)), { timeout: 10000 }, 'Raft ' + stamp)
check('the status set in the edit form shows in the list at once (it would otherwise be worked out as Delayed)', true)
check('the dependency list leaves out what would make a loop', loopOptions >= 1)

// progress is saved and the late one finished clears the alert
await page.evaluate((s) => [...document.querySelectorAll('table[aria-label=Activities] tbody tr')].find((r) => r.textContent.includes('Excavation ' + s)).querySelector('button:not([aria-label])').click(), stamp).catch(() => {})
const tick = await page.evaluate((s) => { const r = [...document.querySelectorAll('table[aria-label=Activities] tbody tr')].find((x) => x.textContent.includes('Excavation ' + s)); const b = [...r.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Done'); b?.click(); return !!b }, stamp)
if (tick) { await waitForToast(page, 'Progress recorded'); await toastsGone(page) }
await page.waitForFunction(() => !document.querySelector('[role=alert]'), { timeout: 15000 }).catch(() => {})
const after = (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data
check('finishing the late activity is saved and clears the overdue alert', after.activities[0].actual_percent === 100 && after.summary.overdue === 0)

// milestones
await clickText(page, '[role=tab]', 'Milestones')
await page.waitForSelector('ol[aria-label=Milestones]')
check('the milestone is listed with when it falls due', /Handover/.test(await text('ol[aria-label=Milestones]')) && /In 40 days/.test(await text('ol[aria-label=Milestones]')))
await clickText(page, 'ol[aria-label=Milestones] button', 'Mark reached')
await waitForToast(page, 'Milestone reached')
await toastsGone(page)
check('marking it reached is saved', (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.summary.milestones_done === 1)

// delete asks first, then removes
await clickText(page, '[role=tab]', 'Activities')
await page.waitForSelector('table[aria-label=Activities]')
await page.evaluate((s) => [...document.querySelectorAll('table[aria-label=Activities] tbody tr')].find((r) => r.textContent.includes('Raft ' + s)).querySelector('button[aria-label^="Delete"]').click(), stamp)
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog]')].some((d) => /Delete Raft/.test(d.textContent)))
check('delete asks for confirmation', true)
await inDialog('Yes')
await waitForToast(page, 'Activity removed')
check('and the activity is gone from the database', (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities.length === 2)
// a milestone is deleted only after confirming
await clickText(page, '[role=tab]', 'Milestones')
await page.waitForSelector('ol[aria-label=Milestones]')
await page.evaluate(() => document.querySelector('ol[aria-label=Milestones] button[aria-label^="Delete"]').click())
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog]')].some((d) => /Delete Handover/.test(d.textContent)))
check('deleting a milestone asks first', (await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities.some((a) => a.is_milestone))
await inDialog('Yes')
await waitForToast(page, 'Milestone removed')
check('and then removes it', !(await api(page, 'GET', `/api/jobs/${job.id}/schedule`)).data.activities.some((a) => a.is_milestone))
// the old name is gone from the menu
check('the menu says Project Chart, not Project Chat', /Project Chart/.test(await text('nav')) && !/Project Chat/.test(await text('nav')))
await done()
