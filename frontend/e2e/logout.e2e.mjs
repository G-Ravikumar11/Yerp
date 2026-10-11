import { api, launch, open, signIn, sleep, BASE } from './lib.mjs'

// Signing out must stick: the login page must not sign the person straight back in.
const { page, check, done } = await launch({ allow: [/^401 /] })
await signIn(page)
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('button[aria-label="Sign out"]')
await page.click('button[aria-label="Sign out"]')
await page.waitForFunction(() => location.pathname.endsWith('/login'), { timeout: 15000 })
await sleep(2500)
check('after Sign out the browser stays on the login page', page.url().includes('/login'), page.url())
check('and no one is signed in any more', (await api(page, 'GET', '/api/client/me')).status === 401 && (await api(page, 'GET', '/api/employee/auth/me')).status === 401)
await page.goto(`${BASE}/next/subcontractors/work-orders`, { waitUntil: 'networkidle2' })
await sleep(1500)
check('opening the app again goes to the login page, not into the app', page.url().includes('/login'), page.url())

// A member of staff, who has two ways back in: their own sign-in and (on a shared browser) the owner's.
const stamp = Date.now().toString().slice(-6)
const email = `out.${stamp}@example.in`
await signIn(page)
const made = await api(page, 'POST', '/api/employees', { first_name: 'Out', last_name: `Test${stamp}`, email, password: 'Passw0rd-QA1', phone: '', job_title: 'Manager', department_id: null, reports_to: null, level: 'L4', role: 'employee', permission_role: 'project_manager', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
check('a staff member was made', made.status === 200, JSON.stringify(made.data).slice(0, 100))
await api(page, 'POST', '/api/client/logout')
const login = await api(page, 'POST', '/api/employee/auth/login', { email, password: 'Passw0rd-QA1' })
check('and signs in', login.status === 200, JSON.stringify(login.data).slice(0, 100))
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('button[aria-label="Sign out"]')
await page.click('button[aria-label="Sign out"]')
await page.waitForFunction(() => location.pathname.endsWith('/login'), { timeout: 15000 })
await sleep(2500)
check('staff Sign out stays on the login page', page.url().includes('/login'), page.url())
check('and nothing is left signed in', (await api(page, 'GET', '/api/client/me')).status === 401 && (await api(page, 'GET', '/api/employee/auth/me')).status === 401)
await done()
