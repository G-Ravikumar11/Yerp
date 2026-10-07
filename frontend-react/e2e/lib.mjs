/**
 * A small harness for driving the built app in a real browser.
 *
 * Not part of the unit tests: it needs the backend running (with a throwaway
 * database - it creates and cancels real records) and a Chromium browser.
 *
 *   BASE_URL   where the backend serves the app   (default http://127.0.0.1:8940)
 *   BROWSER    path to Edge or Chrome              (default: Edge on Windows)
 *   OWNER      "email:password" to sign in with    (default: the demo owner)
 *
 *   npm run build && node e2e/items.e2e.mjs
 */
import puppeteer from 'puppeteer-core'

export const BASE = process.env.BASE_URL || 'http://127.0.0.1:8940'
const BROWSER = process.env.BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const [OWNER_EMAIL, OWNER_PASSWORD] = (process.env.OWNER || 'owner@yprojects.co.in:Passw0rdTest').split(':')

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export async function launch({ width = 1440, height = 1000, allow = [] } = {}) {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: 'new', args: ['--no-sandbox', '--disable-gpu'], defaultViewport: { width, height } })
  const page = await browser.newPage()
  // The book opens as the Excel-style sheet; the suites that drive its entries table ask for the plain list.
  await page.evaluateOnNewDocument(() => { try { localStorage.setItem('yerp.mb.view', 'list') } catch { /* private window */ } })
  const problems = []
  page.on('pageerror', (e) => problems.push('page error: ' + e.message))
  page.on('console', (m) => {
    // A 401 before sign-in is expected; anything else in the console is not.
    if (m.type() === 'error' && !/Failed to load resource|401|Unauthorized/.test(m.text())) problems.push('console: ' + m.text())
  })
  // The server's own words for every refusal, so a failing check can be read.
  page.on('response', async (res) => {
    if (res.status() < 400 || res.status() === 401) return
    let body = ''
    try {
      body = (await res.text()).slice(0, 160)
    } catch {
      // The page moved on before the body was read.
    }
    problems.push(`${res.status()} ${res.request().method()} ${res.url().replace(BASE, '')} ${body}`)
  })
  const results = []
  const check = (name, ok, extra = '') => {
    results.push({ name, ok })
    console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? '  -> ' + extra : ''}`)
    return ok
  }
  const done = async () => {
    // Refusals a test provokes on purpose are listed in `allow`; anything else is a problem.
    const unexpected = problems.filter((p) => !allow.some((re) => re.test(p)))
    console.log('\nbrowser problems:', unexpected.length ? unexpected : 'none')
    const failed = results.filter((r) => !r.ok).length
    console.log(`${results.length - failed}/${results.length} checks passed`)
    await browser.close()
    process.exit(failed || unexpected.length ? 1 : 0)
  }
  return { browser, page, check, done, problems }
}

/** Sign in as the account holder. The cookie is set on the page's origin. */
export async function signIn(page, email = OWNER_EMAIL, password = OWNER_PASSWORD) {
  await page.goto(BASE + '/login.html', { waitUntil: 'domcontentloaded' })
  const status = await page.evaluate(
    async (email, password) => (await fetch('/api/client/login', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })).status,
    email,
    password,
  )
  if (status !== 200) throw new Error('sign-in failed: ' + status)
}

export async function open(page, path) {
  await page.goto(BASE + '/next' + path, { waitUntil: 'networkidle0' })
  await page.waitForSelector('main h1', { timeout: 15000 })
}

/** Call the backend as the signed-in browser does. */
export const api = (page, method, url, body) =>
  page.evaluate(
    async (method, url, body) => {
      const res = await fetch(url, { method, credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
      const text = await res.text()
      let data = null
      try {
        data = JSON.parse(text)
      } catch {
        data = text
      }
      return { status: res.status, data }
    },
    method,
    url,
    body,
  )

export const text = (page, selector) => page.$eval(selector, (e) => e.textContent.replace(/\s+/g, ' ').trim())

export async function clickText(page, selector, label) {
  const ok = await page.evaluate(
    (selector, label) => {
      const el = [...document.querySelectorAll(selector)].find((e) => e.textContent.replace(/\s+/g, ' ').trim() === label || e.textContent.replace(/\s+/g, ' ').trim().startsWith(label))
      if (!el) return false
      el.click()
      return true
    },
    selector,
    label,
  )
  if (!ok) throw new Error(`no ${selector} with text "${label}"`)
}

/* --- The data grid ------------------------------------------------------ */

const rowsOf = (grid) => [...grid.querySelectorAll('[role=row]')].filter((r) => r.querySelector('[role=rowheader]'))

/** Click a cell (row, column) of the nth data grid on the page (or in the open dialog). */
export async function clickCell(page, gridIndex, r, c, scope = '') {
  const pos = await page.evaluate(
    (gridIndex, r, c, scope, rowsFn) => {
      const rowsOf = new Function('grid', 'return ' + rowsFn)()
      const root = scope ? document.querySelector(scope) : document
      const grid = root.querySelectorAll('[role=grid]')[gridIndex]
      const cell = rowsOf(grid)[r].querySelectorAll('[role=gridcell]')[c]
      cell.scrollIntoView({ block: 'nearest', inline: 'nearest' })
      const box = cell.getBoundingClientRect()
      const sc = grid.querySelector('.overflow-auto').getBoundingClientRect()
      const pinned = parseFloat(grid.querySelector('.overflow-auto').style.scrollPaddingLeft) || 0
      const sticky = getComputedStyle(cell).position === 'sticky'
      const left = sticky ? box.left : Math.max(box.left, sc.left + pinned)
      const right = Math.min(box.right, sc.right - 4)
      return { x: (left + right) / 2, y: box.y + box.height / 2 }
    },
    gridIndex,
    r,
    c,
    scope,
    rowsOf.toString(),
  )
  await page.mouse.click(pos.x, pos.y)
}

export const cellText = (page, gridIndex, r, c, scope = '') =>
  page.evaluate(
    (gridIndex, r, c, scope, rowsFn) => {
      const rowsOf = new Function('grid', 'return ' + rowsFn)()
      const root = scope ? document.querySelector(scope) : document
      const grid = root.querySelectorAll('[role=grid]')[gridIndex]
      return rowsOf(grid)[r]?.querySelectorAll('[role=gridcell]')[c]?.textContent.trim()
    },
    gridIndex,
    r,
    c,
    scope,
    rowsOf.toString(),
  )

export const gridRowCount = (page, gridIndex = 0, scope = '') =>
  page.evaluate(
    (gridIndex, scope, rowsFn) => {
      const rowsOf = new Function('grid', 'return ' + rowsFn)()
      const root = scope ? document.querySelector(scope) : document
      return rowsOf(root.querySelectorAll('[role=grid]')[gridIndex]).length
    },
    gridIndex,
    scope,
    rowsOf.toString(),
  )

/** Replace whatever is in a field with a value, the way a person does: select it all and type. */
export async function fill(page, selector, value) {
  await page.click(selector)
  await page.keyboard.down('Control')
  await page.keyboard.press('a')
  await page.keyboard.up('Control')
  if (value) await page.keyboard.type(value)
  else await page.keyboard.press('Backspace')
}

/** Set a field the way React notices (date inputs cannot be typed into reliably in a headless browser). */
export async function setValue(page, selector, value) {
  await page.$eval(
    selector,
    (el, value) => {
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
      el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
    },
    value,
  )
}

/** Wait for every toast to leave - they sit bottom-right and can cover what a test is about to click. */
export const toastsGone = (page, timeout = 12000) => page.waitForFunction(() => !document.querySelector('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]'), { timeout })

/** The body text of the first toast on screen. */
export const toastText = (page) => page.evaluate(() => document.querySelector('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]')?.textContent.trim() ?? '')

export async function waitForToast(page, contains, timeout = 8000) {
  await page.waitForFunction((contains) => [...document.querySelectorAll('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]')].some((e) => e.textContent.includes(contains)), { timeout }, contains)
}

/**
 * An approved work order with a priced schedule, made through the API - the
 * starting point for anything that measures or bills. Returns its id and lines.
 */
export async function approvedOrder(page, { subject = 'E2E order', lines } = {}) {
  const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
  const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
  const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
  const job = vocab.jobs[0]
  let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
  if (!budgets.length) {
    await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'E2E civil', code: 'E2E', allocated_amount: 900000000 })
    budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
  }
  const order = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject, commencement_date: '2026-11-01', completion_date: '2027-03-31', retention_percent: 5, gst_rate: 18, tds_rate: 1 })).data.order
  const boq = lines ?? [
    { activity_no: '1.0', item_description: 'Shuttering for slabs and beams', uom: 'sqm', quantity: 1000, unit_rate: 410, tolerance_percent: 10 },
    { activity_no: '2.0', item_description: 'Reinforcement steel', uom: 'MT', quantity: 20, unit_rate: 68000 },
  ]
  await api(page, 'PUT', `/api/wo/orders/${order.id}/boq`, { lines: boq.map((l) => ({ ...l, budget_id: budgets[0].id })) })
  const ok = await api(page, 'POST', `/api/wo/orders/${order.id}/self-approve`, { comments: 'e2e' })
  if (ok.status !== 200) throw new Error('could not approve the test order: ' + JSON.stringify(ok.data))
  const book = (await api(page, 'GET', `/api/sub-mb/${order.id}`)).data
  return { id: order.id, number: order.wo_number, gang, job, items: book.lines }
}

/** Record a measurement through the API. */
export const measure = (page, orderId, itemId, quantity) => api(page, 'POST', `/api/sub-mb/${orderId}/entries`, { item_id: itemId, quantity, measured_on: '2026-11-15' })

/** Every toast on screen, so a test can say what the person was told. */
export const allToasts = (page) => page.evaluate(() => [...document.querySelectorAll('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]')].map((e) => e.textContent.trim()))

/** The contractor's own bill, attached to a draft bill the way the screen does - a bill cannot be sent without it. */
export function attachHardCopy(page, billId, amount = '') {
  return page.evaluate(async (billId, amount) => {
    const form = new FormData()
    form.append('file', new Blob(['%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'], { type: 'application/pdf' }), 'their_bill.pdf')
    form.append('amount', String(amount))
    const res = await fetch(`/api/sub-bills/${billId}/hardcopy`, { method: 'POST', credentials: 'include', body: form })
    return res.status
  }, billId, amount)
}
