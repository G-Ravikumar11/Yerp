// Every screen on the menu opens for the owner without an error: no failed request, no script error, no error screen,
// no blank page. Nothing about what is on them - the other suites do that - only that each one comes up.
import { BASE, launch, sleep, signIn } from './lib.mjs'

const screens = `/ /approvals /clients/contacts /clients/customers /clients/estimates /clients/measurement /clients/pipeline /clients/work-orders /me/costs /me/documents /me/goals /me/leave /me/onboarding /me/orders /me/payslips /me/profile /me/team /me/timesheet /money/assets /money/gst /money/ledgers /money/owed /money/registers /money/supplier-bills /people/attendance /people/departments /people/employees /people/leave /people/payroll /projects /projects/boq /projects/chat /projects/costs /projects/diary /projects/drawings /projects/equipment /projects/profit /projects/programme /projects/quality /projects/safety /settings /store/enquiries /store/eway /store/goods-receipt /store/items /store/material-costing /store/purchase-orders /store/stock /subcontractors/compliance /subcontractors/measurement-book /subcontractors/ra-bills /subcontractors/vendors /subcontractors/work-orders`.split(' ')

const { page, check, done, problems } = await launch({ width: 1440, height: 900 })
await signIn(page)
for (const path of screens) {
  const before = problems.length
  await page.goto(BASE + '/next' + path, { waitUntil: 'networkidle2', timeout: 30000 }).catch((e) => problems.push('load: ' + e.message))
  await sleep(400)
  const info = await page.evaluate(() => {
    const text = (document.querySelector('main')?.innerText || '').replace(/\s+/g, ' ')
    return { len: text.length, failed: /something went wrong|unexpected error|could not load/i.test(text), snippet: text.slice(0, 80) }
  })
  const mine = problems.splice(before)
  check(`${path} opens cleanly`, mine.length === 0 && info.len > 20 && !info.failed, [...mine.slice(0, 3), info.failed ? info.snippet : ''].filter(Boolean).join(' | '))
}
await done()
