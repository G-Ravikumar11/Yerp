import { api, clickText, fill, launch, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Batch holds, an NCR against a lot, a failed cube result raising its NCR, and the cube dashboard, through the screens.
const { page, check, done } = await launch({ allow: [/409 POST/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const clear = () => toastsGone(page).catch(() => {})
const batchNo = process.env.BATCH_NO

await open(page, '/store/hub/enquiry/batches')
await page.waitForSelector('table[aria-label=Batches]')
await page.waitForFunction((b) => document.querySelector('main')?.textContent.includes(b), { timeout: 15000 }, batchNo)
check('the batch is listed as available', /Available/.test(await text('table[aria-label=Batches]')))
await page.evaluate((b) => [...document.querySelectorAll('table[aria-label=Batches] tbody tr')].find((r) => r.textContent.includes(b)).querySelector('button').click(), batchNo)
await page.waitForSelector('[aria-label="Quality hold"]')
await sleep(600)
await clickText(page, '[role=dialog] button', 'Place batch on hold')
await page.waitForSelector('#bh-why')
await fill(page, '#bh-why', 'Failed moisture check')
await clickText(page, '[role=dialog] button', 'Place on hold')
await waitForToast(page, 'cannot be issued')
await sleep(900)
check('the hold shows with its reason and who placed it', /On Hold/.test(await text('[aria-label="Quality hold"]')) && /Failed moisture check/.test(await text('[aria-label="Hold history"]')))
const id = (await api(page, 'GET', `/api/store/batches?q=${batchNo}`)).data.batches[0].id
const twice = await api(page, 'POST', `/api/store/batches/${id}/hold`, { reason: 'Again' })
check('a second manual hold is refused by the server', twice.status === 409)
await clear()

await clickText(page, '[role=dialog] button', 'Raise NCR')
await page.waitForSelector('#bh-why')
await fill(page, '#bh-why', `Bags damp ${stamp}`)
await page.waitForFunction(() => document.querySelectorAll('#bh-job option').length > 1, { timeout: 15000 })
await page.$eval('#bh-job option[value]:not([value=""])', (o) => o.value).then((v) => setValue(page, '#bh-job', v))
await sleep(300)
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] .grid button')].find((b) => b.textContent.trim() === 'Raise NCR').click())
await waitForToast(page, 'raised')
await sleep(900)
check('the NCR is linked on the batch', /NCR-/.test(await text('[aria-label="Linked NCRs"]')))
const ncrId = (await api(page, 'GET', `/api/store/batches/${id}`)).data.all_ncrs[0].id
await page.keyboard.press('Escape')
await clear()

await open(page, `/projects/quality?ncr=${ncrId}`)
await page.waitForSelector('[aria-label="Store lot"]')
const lot = await text('[aria-label="Store lot"]')
check('the NCR shows the lot, its material and that it is blocked', new RegExp(batchNo).test(lot) && /Blocked from issue/.test(lot) && /available/.test(lot), lot)
await page.keyboard.press('Escape')
await sleep(400)

// a failed cube result
const j = (await api(page, 'POST', '/api/jobs', { name: `Cube site ${stamp}`, customer_name: 'E2E' })).data
await api(page, 'POST', '/api/qc/criteria', { job_id: j.id, grade: 'M25', age_days: 28, min_mean: 25, min_single: 21, standard: 'IS 456' })
const set = (await api(page, 'POST', '/api/qc/cubes', { job_id: j.id, grade: 'M25', cast_on: day(-28), location: 'Raft', test_ages: '28' })).data.cube_set
const today = (await api(page, 'POST', '/api/qc/cubes', { job_id: j.id, grade: 'M30', cast_on: day(-28), location: 'Slab', test_ages: '28' })).data.cube_set
await open(page, '/projects/quality')
await clickText(page, '[role=tab]', 'Cube tests')
await page.waitForSelector('[aria-label="Due today"]')
await sleep(900)
check('the dashboard lists the test due today', new RegExp(today.number).test(await text('table[aria-label="Due today"]')))
const res = await api(page, 'POST', `/api/qc/cubes/${set.id}/results`, { age_days: 28, strengths: '12, 13, 12', tested_on: day(0) })
check('a failed result raises its NCR', res.data.ncr?.status === 'OPEN' && /Automatic Cube Test Failure/.test(res.data.ncr?.origin ?? ''), JSON.stringify(res.data.ncr))
{
  const again = await api(page, 'POST', `/api/qc/cubes/${set.id}/results`, { age_days: 28, strengths: '12, 13, 12', tested_on: day(0) })
  check('the same result again returns the same NCR', again.data.ncr.id === res.data.ncr.id && again.data.repeat === true)
  await open(page, '/projects/quality')
  await clickText(page, '[role=tab]', 'Cube tests')
  await page.waitForSelector('[aria-label="Failed tests"]')
  await sleep(900)
  check('the failed test shows its NCR', new RegExp(res.data.ncr.number).test(await text('table[aria-label="Failed tests"]')))
}
await clickText(page, 'main button', 'Notices')
await page.waitForSelector('table[aria-label="Notice history"]')
check('the notice history opens', true)
await page.keyboard.press('Escape')

await page.setViewport({ width: 390, height: 800 })
for (const path of ['/store/hub/enquiry/batches', '/projects/quality']) {
  await open(page, path)
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check(`${path} fits a phone`, over <= 1, String(over))
}
await done()
