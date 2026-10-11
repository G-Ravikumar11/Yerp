import { launch, open, signIn, sleep } from './lib.mjs'

const { page, check, done } = await launch({ width: 1440, height: 900 })
await signIn(page)
await open(page, '/')
await sleep(600)

// Expanded: every entry reads as a row, and the page we are on is marked.
const rows = () =>
  page.evaluate(() =>
    [...document.querySelectorAll('nav[aria-label="Main"] > div > *')].map((el) => {
      const r = el.getBoundingClientRect()
      const svg = el.querySelector('svg')?.getBoundingClientRect()
      return { h: Math.round(r.height), cx: svg ? Math.round(svg.left + svg.width / 2) : null, label: el.textContent.trim() }
    }),
  )
const open_ = await rows()
check('every sidebar entry is a full-height row', open_.every((r) => r.h >= 40), JSON.stringify(open_.map((r) => r.h)))
check('the page we are on is highlighted in the sidebar', (await page.$('nav[aria-label="Main"] a[aria-current="page"] > span.absolute')) !== null)

// Collapsed: the entries must keep their height and sit on one centre line. A tooltip wrapped round a link once
// turned the link's class into text, which squeezed the plain links to 18px and left their icons off to the side.
await page.click('button[aria-label="Collapse sidebar"]')
await sleep(900)
const shut = await rows()
check('collapsed, every entry is still a full-height row', shut.every((r) => r.h === 40), JSON.stringify(shut.map((r) => r.h)))
check('collapsed, every icon is on the same centre line', new Set(shut.map((r) => r.cx)).size === 1, JSON.stringify(shut.map((r) => r.cx)))
const classes = await page.$$eval('nav[aria-label="Main"] a', (as) => as.map((a) => a.className))
check('collapsed links carry real classes, not code', classes.length > 0 && classes.every((c) => !c.includes('=>') && c.includes('h-10')))
await done()
