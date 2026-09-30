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

export async function launch({ width = 1440, height = 1000 } = {}) {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: 'new', args: ['--no-sandbox', '--disable-gpu'], defaultViewport: { width, height } })
  const page = await browser.newPage()
  const problems = []
  page.on('pageerror', (e) => problems.push('page error: ' + e.message))
  page.on('console', (m) => {
    // A 401 before sign-in is expected; anything else in the console is not.
    if (m.type() === 'error' && !/401|Unauthorized/.test(m.text())) problems.push('console: ' + m.text())
  })
  const results = []
  const check = (name, ok, extra = '') => {
    results.push({ name, ok })
    console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? '  -> ' + extra : ''}`)
    return ok
  }
  const done = async () => {
    console.log('\nbrowser problems:', problems.length ? problems : 'none')
    const failed = results.filter((r) => !r.ok).length
    console.log(`${results.length - failed}/${results.length} checks passed`)
    await browser.close()
    process.exit(failed || problems.length ? 1 : 0)
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

/** The body text of the first toast on screen. */
export const toastText = (page) => page.evaluate(() => document.querySelector('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]')?.textContent.trim() ?? '')

export async function waitForToast(page, contains, timeout = 8000) {
  await page.waitForFunction((contains) => [...document.querySelectorAll('[aria-live=polite] [role=status], [aria-live=polite] [role=alert]')].some((e) => e.textContent.includes(contains)), { timeout }, contains)
}
