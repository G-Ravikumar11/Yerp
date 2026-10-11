// The pages that are not behind the ERP's menu: sign-in, reset, onboarding, the partner portal, the platform console, careers, a meeting.
import { BASE, launch, sleep } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/404 GET \/api\/(public\/jobs|recruitment\/form)/, /400 POST \/api\/client\/login/, /401/, /403/] })
const text = () => page.$eval('body', (b) => b.textContent.replace(/\s+/g, ' '))
const go = async (path, wait = 'h1') => { await page.goto(BASE + path, { waitUntil: 'networkidle0' }); await page.waitForSelector(wait, { timeout: 15000 }) }

// An old address is forwarded, with its query.
await page.goto(BASE + '/login.html?error=account_disabled', { waitUntil: 'networkidle0' })
check('the old sign-in address forwards to the React page', page.url() === BASE + '/next/login?error=account_disabled', page.url())
check('and shows the message for the error in the link', /That account has been disabled/.test(await text()))

// Wrong password says so; the right one lands in the app.
await go('/next/login')
await page.type('#email', 'nobody@example.com')
await page.type('#password', 'wrong-password')
await page.click('button[type=submit]')
await page.waitForFunction(() => /did not match an account/.test(document.body.textContent))
check('a wrong password is refused in words', true)
await go('/next/login')
await page.type('#email', 'owner@yprojects.co.in')
await page.type('#password', 'Passw0rdTest')
await page.click('button[type=submit]')
await page.waitForFunction(() => location.pathname === '/next/', { timeout: 15000 })
check('the right one opens the app', page.url().startsWith(BASE + '/next/') && !/login/.test(page.url()), page.url())

// A dead reset link is told so before any password is typed.
await go('/next/reset-password?token=not-a-real-token')
await page.waitForFunction(() => /invalid or has expired/.test(document.body.textContent))
check('a dead reset link says so', true)
await go('/next/reset-password')
check('a reset page with no token says so', /invalid or has expired/.test(await text()))

// The partner portal door, the platform console door, careers and the application form.
await page.evaluate(() => fetch('/api/client/logout', { method: 'POST' }))
await go('/next/portal')
check('the partner portal shows its own sign-in', /Partner portal/.test(await text()) && !!(await page.$('#pl-email')))
await go('/next/superadmin/login')
check('the platform console has its own sign-in', /Super Admin/.test(await text()) && !!(await page.$('#login-id')))
await go('/next/superadmin/login?error=not_admin')
check('and explains a Google account that is not an admin', /not registered as a super admin/.test(await text()))
await go('/next/jobs')
check('careers with no company in the link says what is missing', /needs a company reference/.test(await text()))
await go('/next/apply')
check('an application with no link says so', /No form link provided/.test(await text()))
await go('/next/jobs?c=no-such-company', 'main')
await page.waitForFunction(() => /could not load these roles/.test(document.body.textContent))
check('careers for an unknown company says it could not load', true)

// A meeting is for signed-in people: signed out it goes to sign-in and comes back.
await page.goto(BASE + '/next/meeting?room=abc', { waitUntil: 'networkidle0' })
check('a meeting sends a signed-out person to sign in, then back', /\/next\/login\?next=/.test(page.url()), page.url())
await sleep(200)
await done()
