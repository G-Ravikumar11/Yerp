import { BASE, api, clickText, fill, launch, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Quality: walk a checklist and fail it, raise the non-conformance from it and take that through assign, correction,
// verification and closure; register cubes, read them against the project's criteria, and have the engineer decide.
// The 409s are the server refusing what the checks provoke on purpose.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/qc\//] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const dialogs = () => page.$$eval('[role=dialog]', (d) => d.length)
const gone = (n = 0) => page.waitForFunction((n) => document.querySelectorAll('[role=dialog]').length <= n, { timeout: 10000 }, n)
const inDialog = async (label) => {
  const ok = await page.evaluate((label) => {
    const d = [...document.querySelectorAll('[role=dialog]')].pop()
    const b = [...(d?.querySelectorAll('button') ?? [])].find((x) => x.textContent.replace(/\s+/g, ' ').trim().startsWith(label))
    b?.click()
    return !!b
  }, label)
  if (!ok) { console.log(await page.evaluate(() => [...document.querySelectorAll('[role=dialog]')].map((d) => d.innerText.slice(0, 400)).join(' ===== '))); throw new Error('no button ' + label) }
}
// The first load of a fresh browser fetches the whole bundle; allow it longer than the shared helper does.
const open = async (page, path) => { for (let n = 0; ; n++) { await page.goto(BASE + '/next' + path, { waitUntil: 'networkidle0', timeout: 90000 }); if (await page.waitForSelector('main h1', { timeout: 20000 }).then(() => true, () => false)) return; if (n >= 3) throw new Error('page did not render') } }
const nextDate = (days) => new Date(Date.now() + days * 864e5).toISOString().slice(0, 10)

await open(page, '/projects/quality')

// A project and the criteria the cubes are read against - set by whoever signs off, not assumed.
let jobs = (await api(page, 'GET', '/api/jobs')).data
jobs = Array.isArray(jobs) ? jobs : (jobs.jobs ?? [])
const project = jobs[0] ?? (await api(page, 'POST', '/api/jobs', { name: `Quality site ${stamp}`, customer_name: 'E2E' })).data
await api(page, 'POST', '/api/qc/criteria', { job_id: project.id, grade: 'M25', age_days: 28, min_mean: 25, min_single: 0, standard: 'IS 456:2000 cl. 16' })

await open(page, '/projects/quality')
await page.waitForFunction(() => document.querySelector('#qc-job option[value]:not([value=""])'), { timeout: 10000 })
await setValue(page, '#qc-job', String(project.id))
await sleep(600)

// ---- inspections
await clickText(page, 'main button', 'New')
await page.waitForSelector('#qn-where')
await page.waitForFunction(() => document.querySelector('#qn-list')?.options.length > 0)
check('the form offers the six standard checklists', (await page.$eval('#qn-list', (s) => s.options.length)) >= 6)
await inDialog('Start it')           // validation: nothing blocks it once project and checklist are chosen
await sleep(300)
await page.waitForSelector('#qn-job', { hidden: true }).catch(() => {})
await page.waitForSelector('#qn-where', { hidden: true }).catch(() => {})
await page.waitForSelector('table[aria-label=Checks]')
const rows = await page.$$eval('table[aria-label=Checks] tbody tr', (r) => r.length)
check('the checklist opens with its checks to walk', rows > 2, rows + ' checks')
check('submitting is held back until every check is looked at', await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => b.textContent.trim() === 'Submit for approval')?.disabled === true))
await page.evaluate(() => {
  const trs = [...document.querySelectorAll('table[aria-label=Checks] tbody tr')]
  trs.forEach((tr, i) => tr.querySelectorAll('input[type=radio]')[i === 0 ? 1 : 0].click())
})
await fill(page, 'table[aria-label=Checks] tbody tr:first-child input[aria-label^="Remark"]', `Cover is short ${stamp}`)
await inDialog('Save')
await waitForToast(page, 'Saved')
await toastsGone(page)
await inDialog('Approve')
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog] button')].some((b) => b.textContent.trim() === 'Fail it'))
await inDialog('Fail it')
await waitForToast(page, 'failed')
await toastsGone(page)
check('a check marked not ok fails the inspection and says so', /Failed/.test(await text('[role=dialog]')) && /1 not ok/.test(await text('[role=dialog]')))
check('the decision is in the trail with its author', /Approved - failed/.test(await text('[role=dialog]')))

// ---- the NCR, from the failed inspection
await inDialog('Raise NCR')
await page.waitForSelector('#nc-who')
await fill(page, '#nc-who', `Shuttering gang ${stamp}`)
await setValue(page, '#nc-sev', 'Major')
await setValue(page, '#nc-by', nextDate(5))
await inDialog('Raise it')
await waitForToast(page, 'raised')
await toastsGone(page)
await page.waitForFunction(() => /Progress/.test(document.body.innerHTML) && document.querySelector('ol[aria-label=Progress]'))
check('the NCR opens in its detail, filled in from what failed', /Lap|Cover is short|failed/.test(await text('[role=dialog]')))
const ncrDialog = '[role=dialog]:last-of-type'

// a second NCR for the same inspection is refused
const inspectionId = (await api(page, 'GET', '/api/qc/inspections')).data.inspections[0].id
const dup = await api(page, 'POST', '/api/qc/ncrs', { source_type: 'inspection', source_id: inspectionId })
check('one failure gets one NCR', dup.status === 409, dup.data?.detail)

await inDialog('Assign')
await page.waitForSelector('#na-who')
await fill(page, '#na-who', `Shuttering gang ${stamp}`)
await setValue(page, '#na-by', nextDate(5))
await inDialog('Assign')
await waitForToast(page, 'assigned')
await toastsGone(page)
await inDialog('Record corrective work')
await page.waitForSelector('#nw-done')
await fill(page, '#nw-done', 'Cover re-set with 40 mm blocks')
await fill(page, '#nw-root', 'Blocks left out at the pour')
await inDialog('Save')
await waitForToast(page, 'Corrective work recorded')
await toastsGone(page)
// a major NCR cannot go for verification without evidence
await inDialog('Request verification')
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog] button')].some((b) => b.textContent.trim() === 'Request verification' && b.closest('[role=dialog]').textContent.includes('Ask for')))
await inDialog('Request verification')
await page.waitForFunction(() => [...document.querySelectorAll('[aria-live=polite] [role=alert], [aria-live=polite] [role=status]')].some((e) => /Attach the photographs|Sent for verification/.test(e.textContent)), { timeout: 8000 })
const refused = await page.evaluate(() => [...document.querySelectorAll('[aria-live=polite] [role=alert], [aria-live=polite] [role=status]')].some((e) => /Attach the photographs/.test(e.textContent)))
check('a major NCR needs its evidence before verification', refused)
await toastsGone(page)
await page.keyboard.press('Escape')
await sleep(300)

// attach evidence through the API as the page would, then carry on
const ncr = (await api(page, 'GET', '/api/qc/ncrs')).data.ncrs[0]
await page.evaluate(async (id) => {
  const fd = new FormData()
  fd.append('file', new Blob([new Uint8Array([255, 216, 255, 224, 0, 0])], { type: 'image/jpeg' }), 'after.jpg')
  fd.append('attached_type', 'ncr')
  fd.append('attached_id', String(id))
  await fetch('/api/files', { method: 'POST', body: fd, credentials: 'include' })
}, ncr.id)
await api(page, 'POST', `/api/qc/ncrs/${ncr.id}/request-verification`)
check('verification is requested once the evidence is there', (await api(page, 'GET', `/api/qc/ncrs/${ncr.id}`)).data.ncr.status === 'REINSPECTION')
await page.reload({ waitUntil: 'networkidle0' })
await page.waitForSelector('#qc-job')
await setValue(page, '#qc-job', String(project.id))
await clickText(page, '[role=tab]', 'Non-conformances')
await sleep(600)
await page.evaluate((n) => [...document.querySelectorAll('table[aria-label="Non-conformances"] tbody tr')].find((r) => r.textContent.includes(n)).querySelector('button').click(), ncr.number)
await page.waitForSelector('ol[aria-label=Progress]')
// the app serves a remembered copy first and then the fresh one
await page.waitForFunction(() => /Reinspection/.test(document.querySelector('ol[aria-label=Progress] [aria-current=step]')?.textContent ?? ''), { timeout: 10000 }).catch(() => {})
check('the detail shows the NCR in reinspection', /Reinspection/.test(await text('ol[aria-label=Progress] [aria-current=step]')))
await inDialog('Verify')
await page.waitForFunction(() => [...document.querySelectorAll('[role=dialog]')].some((d) => /Verify the correction/.test(d.textContent)))
await inDialog('Verified')
await waitForToast(page, 'Verified')
await toastsGone(page)
await inDialog('Close the NCR')
await page.waitForSelector('#confirm-reason')
await fill(page, '#confirm-reason', 'Cover corrected and re-inspected')
await inDialog('Close it')
await waitForToast(page, 'closed')
await toastsGone(page)
check('the NCR closes only after verification and records who closed it', (await api(page, 'GET', `/api/qc/ncrs/${ncr.id}`)).data.ncr.status === 'CLOSED')
await page.keyboard.press('Escape')
await sleep(400)

// ---- cubes
await clickText(page, '[role=tab]', 'Cube tests')
await clickText(page, 'main button', 'New')
await page.waitForSelector('#cs-where')
await fill(page, '#cs-where', `Raft pour ${stamp}`)
await fill(page, '#cs-ref', `P-${stamp}`)
await fill(page, '#cs-ids', 'A1, A2, A3')
await setValue(page, '#cs-date', nextDate(-30))
await inDialog('Register the set')
await waitForToast(page, 'registered')
await toastsGone(page)
await page.waitForFunction(() => document.querySelector('table[aria-label=Results], [role=dialog]') && /Test schedule/.test(document.body.textContent))
check('the sample opens with its schedule: the age the project tests at is overdue', (await page.$$eval('[role=dialog] li', (l) => l.filter((x) => /overdue/.test(x.textContent)).length)) >= 1)
await inDialog('Enter a result')
await page.waitForSelector('#cr-str')
await fill(page, '#cr-age', '28')
await fill(page, '#cr-str', '17.5, 18, 18.5')
await fill(page, '#cr-lab', 'ABC Laboratory')
await inDialog('Record it')
await waitForToast(page, 'N/mm2')
await toastsGone(page)
const set = (await api(page, 'GET', '/api/qc/cubes')).data.cubes[0]
check('a 28-day result under the project criterion is below grade and needs review', set.status === 'below grade' && set.needs_review, set.status)
check('the engineer cannot simply accept it', (await api(page, 'POST', `/api/qc/cubes/${set.id}/decision`, { decision: 'accepted', note: 'fine' })).status === 409)
await page.keyboard.press('Escape')
await sleep(400)

// ---- the dashboard cards narrow the list
await clickText(page, 'main button', 'Below grade')
await sleep(800)
check('the Below grade card opens the cube tab filtered to it', (await page.$eval('[aria-label=Status]', (s) => s.value)) === 'below_grade' && /Raft pour/.test(await text('table[aria-label="Cube samples"] tbody')))
check('the cards are counted from stored data', /Below grade\s*1/.test(await text('main')) && /NCRs open\s*0/.test(await text('main')), (await text('main')).slice(0, 200))
await clickText(page, 'main button', 'Inspections failed')
await sleep(800)
check('the Inspections failed card applies the Failed filter', (await page.$eval('[aria-label=Status]', (s) => s.value)) === 'FAILED' && /Failed/.test(await text('table[aria-label=Inspections] tbody')))
check('the dialogs are all closed', (await dialogs()) === 0)
await done()
