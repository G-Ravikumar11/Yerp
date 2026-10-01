import { allToasts, api, approvedOrder, clickText, launch, measure, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// The whole life of a work order, as the owner meets it: raise it, approve it, measure and bill it, then amend it
// (twice, by two different routes) and see that every revision can go for approval, or be approved by the owner
// who raised it - and that the work already done moves across.
const { page, check, done } = await launch({ allow: [/40[039] /] })
await signIn(page)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const buttons = () => page.$$eval('main button', (b) => b.map((x) => x.textContent.trim()).filter(Boolean))
const order = (id) => api(page, 'GET', `/api/wo/orders/${id}`).then((r) => r.data.order)
const stamp = Date.now().toString().slice(-6)
const dialogDone = () => page.waitForFunction(() => !document.querySelector('[role=dialog], [role=alertdialog]'), { timeout: 10000 })
const confirm = async (label) => {
  await page.waitForSelector('[role=dialog], [role=alertdialog]')
  await page.evaluate((label) => { const d = [...document.querySelectorAll('[role=dialog], [role=alertdialog]')].pop(); [...d.querySelectorAll('button')].filter((b) => b.textContent.trim() === label).pop().click() }, label)
}
const openOrder = async (id) => { await page.evaluate(() => indexedDB.deleteDatabase('keyval-store')); await open(page, `/subcontractors/work-orders/${id}`); await sleep(400) }

// --- 1. A new order, as a draft: the owner may send it up, or approve it as raised ----------------------------------
const base = await approvedOrder(page, { subject: `E2E flow ${stamp}` }) // self-approved through the API
const items = base.items
await measure(page, base.id, items[0].item_id, 100)
await measure(page, base.id, items[1].item_id, 4)
check('an order the owner raised and approved is live', (await order(base.id)).status === 'APPROVED')

// --- 2. A bill certified on it, and one still open ---------------------------------------------------------------------------------------
const bill1 = (await api(page, 'POST', '/api/sub-bills', { order_id: base.id })).data.bill
await api(page, 'POST', `/api/sub-bills/${bill1.id}/submit`, {})
const cert = await api(page, 'POST', '/api/approvals/decide', { kind: 'sub_bill', id: bill1.id, decision: 'approve', note: '', override: false })
check('a bill is certified against the order', cert.status === 200, JSON.stringify(cert.data).slice(0, 100))
await measure(page, base.id, items[0].item_id, 50)
const bill2 = (await api(page, 'POST', '/api/sub-bills', { order_id: base.id })).data.bill // a draft left open

// --- 3. Amend: the revision is a draft; the owner is offered both ways to take it forward --------------------------------
await openOrder(base.id)
await clickText(page, 'main button', 'Amend')
await confirm('Open a revision')
await page.waitForFunction((id) => !location.pathname.endsWith('/' + id), { timeout: 10000 }, base.id)
await sleep(800)
const rev1 = Number(page.url().match(/work-orders\/(\d+)/)[1])
const b1 = await buttons()
check('the revision opens as a draft, with Submit for approval AND Approve and issue for the owner', (await order(rev1)).status === 'DRAFT' && b1.includes('Submit for approval') && b1.includes('Approve and issue'), b1.join(' | '))
check('the original stays live until the revision is approved', (await order(base.id)).status === 'APPROVED')

check('the revision says on its own page what is stopping it, before anyone clicks', /cannot be approved yet/.test(await text('main')) && /still open/.test(await text('main')), (await text('main')).slice(0, 200))
// --- 4. An open bill on the old order blocks the revision - and says so -------------------------------------------------------------
await clickText(page, 'main button', 'Approve and issue')
await confirm('Approve')
await sleep(1200)
const refusal = (await allToasts(page)).join(' / ')
check('with a bill still open, approving is refused in plain words, and the revision stays a draft', /still open|Certify or cancel/i.test(refusal) && (await order(rev1)).status === 'DRAFT', refusal)
await toastsGone(page)
await api(page, 'POST', `/api/sub-bills/${bill2.id}/cancel`, { comments: 'e2e' })

// --- 5. Sent for approval, then approved by the owner ------------------------------------------------------------------------------------
await openOrder(rev1)
await clickText(page, 'main button', 'Submit for approval')
await waitForToast(page, 'submitted for approval')
await sleep(800)
const b2 = await buttons()
check('submitted, the owner is offered Approve and Send back', (await order(rev1)).status === 'PROVISIONAL' && b2.includes('Approve') && b2.includes('Send back'), b2.join(' | '))
const inbox = (await api(page, 'GET', '/api/approvals/inbox')).data.items
check('and it is in the approvals inbox', inbox.some((i) => i.kind === 'subcontract_order' && i.id === rev1))
await clickText(page, 'main button', 'Approve')
await confirm('Approve')
await waitForToast(page, 'approved')
await dialogDone()
await sleep(600)
const after1 = await order(rev1)
check('approved: the revision is live and the original is amended', after1.status === 'APPROVED' && (await order(base.id)).status === 'AMENDED', `${after1.status}`)
const moved = (await api(page, 'GET', `/api/sub-mb/${rev1}`)).data
check('the measurements and the certified bill moved to the revision', moved.lines.some((l) => l.measured_to_date > 0) && (await api(page, 'GET', `/api/sub-bills?order_id=${rev1}`)).data.bills.length >= 1, JSON.stringify(moved.lines.map((l) => l.measured_to_date)))
await toastsGone(page)

// --- 6. Amend again; the owner sends it back to itself, then approves it as raised ----------------------------------------
await openOrder(rev1)
await clickText(page, 'main button', 'Amend')
await confirm('Open a revision')
await page.waitForFunction((id) => !location.pathname.endsWith('/' + id), { timeout: 10000 }, rev1)
await sleep(800)
const rev2 = Number(page.url().match(/work-orders\/(\d+)/)[1])
await clickText(page, 'main button', 'Submit for approval')
await waitForToast(page, 'submitted for approval')
await toastsGone(page)
await sleep(600)
await clickText(page, 'main button', 'Send back')
await page.waitForSelector('[role=dialog] textarea, [role=alertdialog] textarea')
await page.type('[role=dialog] textarea, [role=alertdialog] textarea', 'Rate on line 2 to be checked')
await confirm('Send back')
await sleep(1000)
const sent = await order(rev2)
check('sent back, it returns to a draft carrying the reason', sent.status === 'DRAFT' && /Rate on line 2/.test(sent.rejection_reason || ''), `${sent.status} ${sent.rejection_reason}`)
await toastsGone(page)
await openOrder(rev2)
const b3 = await buttons()
check('and the owner can send it up again or approve it as raised', b3.includes('Submit for approval') && b3.includes('Approve and issue'), b3.join(' | '))
await clickText(page, 'main button', 'Approve and issue')
await confirm('Approve')
await waitForToast(page, 'approved')
await dialogDone()
await sleep(600)
check('approved as issued: the second revision is live and the first is amended', (await order(rev2)).status === 'APPROVED' && (await order(rev1)).status === 'AMENDED')
await toastsGone(page)

// --- 7. A member of staff amends: it goes up the line, and the owner may step in ---------------------------------------------
const mgr = await api(page, 'POST', '/api/employees', { first_name: 'Mgr', last_name: `Flow${stamp}`, email: `mgr.flow.${stamp}@example.in`, password: 'Passw0rd-QA1', phone: '', job_title: 'Project manager', department_id: null, reports_to: null, level: 'L4', role: 'employee', permission_role: 'project_manager', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
const pb = await api(page, 'POST', '/api/employees', { first_name: 'Plan', last_name: `Flow${stamp}`, email: `plan.flow.${stamp}@example.in`, password: 'Passw0rd-QA1', phone: '', job_title: 'Planning', department_id: null, reports_to: mgr.data.id, level: 'L2', role: 'employee', permission_role: 'planning_billing', site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
await api(page, 'POST', '/api/client/logout')
await api(page, 'POST', '/api/employee/auth/login', { email: `plan.flow.${stamp}@example.in`, password: 'Passw0rd-QA1' })
const staffRev = (await api(page, 'POST', `/api/wo/orders/${rev2}/amend`, {})).data.order
check('a member of staff who may draft work orders can amend one', staffRev?.status === 'DRAFT', staffRev?.wo_number)
const selfTry = await api(page, 'POST', `/api/wo/orders/${staffRev.id}/self-approve`, {})
check('but cannot approve their own work: that is for somebody else', selfTry.status === 401 || selfTry.status === 403, String(selfTry.status))
await openOrder(staffRev.id)
check('and is not offered Approve and issue', !(await buttons()).includes('Approve and issue') && (await buttons()).includes('Submit for approval'), (await buttons()).join(' | '))
await clickText(page, 'main button', 'Submit for approval')
await waitForToast(page, 'submitted for approval')
await sleep(600)
const routed = await order(staffRev.id)
check('submitted, it waits first on the manager the owner set for them', routed.status === 'PROVISIONAL' && (routed.approval_route || []).length >= 2 && (routed.approval_route || [])[0]?.name.includes('Flow' + stamp) && routed.approval_route[0].status === 'waiting', JSON.stringify(routed.approval_route))
await api(page, 'POST', '/api/employee/auth/logout')
await signIn(page)
const seen = (await api(page, 'GET', '/api/approvals/inbox')).data.items.find((i) => i.kind === 'subcontract_order' && i.id === staffRev.id)
check('the owner sees it, with whose desk it is on, and may decide it', !!seen && seen.mine === false && !!seen.waiting_on, JSON.stringify(seen && [seen.mine, seen.waiting_on]))
await openOrder(staffRev.id)
check('and on its own page the owner is offered Approve and Send back', (await buttons()).includes('Approve') && (await buttons()).includes('Send back'), (await buttons()).join(' | '))
await clickText(page, 'main button', 'Approve')
await confirm('Approve')
await waitForToast(page, 'approved')
await dialogDone()
await sleep(600)
check('the owner stepping in approves it, and the line before them is passed', (await order(staffRev.id)).status === 'APPROVED' && (await order(rev2)).status === 'AMENDED')

// --- 8. The Measurement Book lists the live revision, and keeps the amended ones -------------------------------------------------------
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await open(page, `/subcontractors/measurement-book?order=${staffRev.id}`)
await sleep(1000)
const shown = await text('main')
check('the Measurement Book opens on the live revision with the work carried across', shown.includes((await order(staffRev.id)).wo_number) && /Measured/i.test(shown))
await done()
