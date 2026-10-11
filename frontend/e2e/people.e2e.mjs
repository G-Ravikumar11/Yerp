import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// People: the owner creates a department and an employee in it; it shows on work orders, and on the employee's own sign-in.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const dept = `QA Roads ${stamp}`
const dialog = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))

await open(page, '/people/departments')
await page.waitForSelector('main h1')
await clickText(page, 'button', 'New department')
await page.waitForSelector('#dp-name')
await fill(page, '#dp-name', dept)
await fill(page, '#dp-desc', 'Road and drain works')
await page.click('button[aria-label="hard-hat"]')
await clickText(page, 'button', 'Save department')
await waitForToast(page, 'created')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)
await sleep(500)
check('the department is created and shown with nobody in it yet', await page.evaluate((d) => !!document.querySelector(`section[aria-label="${d}"]`) && document.querySelector(`section[aria-label="${d}"]`).textContent.includes('0 people'), dept))

// It is offered on a work order
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
check('the work order departments are the ones created, not a fixed list', vocab.departments.includes(dept) && !vocab.departments.includes('Plumbing'), vocab.departments.join(', '))

// An employee in it, with a login
await open(page, '/people/employees')
await page.waitForSelector('table[aria-label=Employees]')
await clickText(page, 'button', 'Add an employee')
await page.waitForSelector('#ef-first')
const email = `qa.roads.${stamp}@example.in`
await fill(page, '#ef-first', 'Asha')
await fill(page, '#ef-last', `Roads${stamp}`)
await page.evaluate(() => { const e = document.querySelector('#ef-email'); e.focus() })
await fill(page, '#ef-email', email)
await fill(page, '#ef-pass', 'Passw0rd-QA1')
await fill(page, '#ef-title', 'Site engineer')
const deptId = (await api(page, 'GET', '/api/departments')).data.find((d) => d.name === dept).id
await setValue(page, '#ef-dept', String(deptId))
await clickText(page, 'button', 'Create the employee')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('Give these to'), { timeout: 10000 })
check('the login is shown once, to hand over', (await dialog()).includes(email) && (await dialog()).includes('Passw0rd-QA1') && (await dialog()).includes('EMP-'), (await dialog()).slice(0, 160))
await clickText(page, '[role=dialog] button', 'Done')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)

await page.evaluate((n) => document.querySelector('input[aria-label=Search]')?.focus(), '')
await fill(page, 'input[aria-label=Search]', `Roads${stamp}`)
await sleep(500)
const row = await page.$eval('table[aria-label=Employees] tbody', (e) => e.textContent.replace(/\s+/g, ' '))
check('the employee is listed in that department', row.includes(dept) && row.includes('Site engineer'), row)

// What the staff member sees when they sign in
const staffMe = await page.evaluate(async (email) => {
  const login = await fetch('/api/employee/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'Passw0rd-QA1' }) })
  if (!login.ok) return { error: login.status }
  return await (await fetch('/api/employee/auth/me')).json()
}, email)
check("the department the owner chose is on the staff member's own sign-in", staffMe.department === dept, JSON.stringify({ d: staffMe.department, e: staffMe.error }))

await done()
