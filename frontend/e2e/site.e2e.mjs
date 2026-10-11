// The company's public front page, now a page of the React app: its sections, the project index, the quote brief and the way in to the ERP.
import { BASE, launch, sleep } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/WebGL/i, /GPU/i] })
const body = () => page.$eval('body', (b) => b.textContent.replace(/\s+/g, ' '))
await page.goto(BASE + '/', { waitUntil: 'networkidle0' })
await page.waitForSelector('.hero__title')

check('the front page is served at the root with its own title', (await page.title()).startsWith('Yalavarti Projects'), await page.title())
check('and a description a search engine can read without running the page', await page.evaluate(() => /Hyderabad, since 1998/.test(document.querySelector('meta[name=description]')?.content ?? '')))
check('every section is there', await page.evaluate(() => ['top', 'clients', 'capabilities', 'systems', 'work', 'projects', 'company', 'quote', 'contact'].every((id) => document.getElementById(id))))
check('the ERP is one click away from the top bar', await page.evaluate(() => document.querySelector('.nav__login')?.getAttribute('href') === '/next/login'))
check('the ERP styles are not on the company page', await page.evaluate(() => getComputedStyle(document.body).backgroundColor === 'rgb(0, 0, 0)'))

// The project index: sector chips, search, and show more.
check('the index starts with the first ten of all projects', /Showing 10 of 91/.test(await body()))
await page.evaluate(() => [...document.querySelectorAll('#pchips .chip')].find((c) => c.textContent.startsWith('Hospitality')).click())
await page.waitForFunction(() => /Showing 2 of 2 · Hospitality/.test(document.body.textContent))
check('a sector chip narrows the list', true)
await page.evaluate(() => [...document.querySelectorAll('#pchips .chip')].find((c) => c.textContent.startsWith('All')).click())
await page.type('#psearch', 'metro')
await page.waitForFunction(() => /Showing \d+ of \d+/.test(document.querySelector('#presult').textContent) && !/of 91/.test(document.querySelector('#presult').textContent))
check('searching by a word narrows it', true, await page.$eval('#presult', (e) => e.textContent))
await page.focus('#psearch')
for (let i = 0; i < 5; i++) await page.keyboard.press('Backspace')
await page.waitForFunction(() => /of 91/.test(document.querySelector('#presult').textContent))
await page.click('#pmore')
await page.waitForFunction(() => /Showing 20 of 91/.test(document.querySelector('#presult').textContent))
check('Show More adds ten', true)

// Picking a city on the map filters the list; Show All puts it back.
const pin = await page.$('#mapsvg .pin:nth-of-type(1)')
if (await page.evaluate(() => getComputedStyle(document.querySelector('#mapsvg')).display !== 'none')) {
  await page.evaluate(() => [...document.querySelectorAll('#mapsvg .pin')].find((p) => /^Chennai/.test(p.getAttribute('aria-label'))).dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await page.waitForFunction(() => /in Chennai/.test(document.querySelector('#presult').textContent))
  check('picking Chennai on the map filters the projects to Chennai', true)
  await page.click('#mapclear')
  await page.waitForFunction(() => !/in Chennai/.test(document.querySelector('#presult').textContent))
  check('Show All clears it', true)
} else check('the 3D map is showing in place of the flat one', await page.evaluate(() => document.querySelector('.atlas__map').classList.contains('is3d')))
void pin

// The 3D building's controls follow what is picked.
await page.evaluate(() => document.getElementById('systems').scrollIntoView())
await page.evaluate(() => [...document.querySelectorAll('#sysbtns button')].find((b) => b.textContent.includes('Fire')).click())
check('picking Fire Protection describes it', /Fire water storage/.test(await body()) && (await page.$eval('#sysk', (e) => e.textContent)) === 'Fire Protection')
await page.click('#sysadd')
check('a system can be added to the quote from the building', await page.evaluate(() => /Fire fighting added to your quote/.test(document.getElementById('toast').textContent)))

// The quote brief builds as the visitor answers.
await page.evaluate(() => document.getElementById('quote').scrollIntoView())
check('the fire scope picked above shows in the brief', await page.evaluate(() => /Fire fighting/.test(document.getElementById('brieflist').textContent)))
await page.click('input[name=type][value=res]')
await page.type('#qcity', 'Hyderabad')
await page.evaluate(() => document.querySelector('input[name=stage][value="Under construction"]').click())
await page.waitForFunction(() => /comparable residential project/.test(document.getElementById('briefsimilar').textContent))
check('comparable projects appear once a type is chosen', true, await page.$eval('#briefsimilar', (e) => e.textContent.slice(0, 80)))
await page.waitForFunction(() => /Hyderabad/.test(document.getElementById('brieflist').textContent))
const href = await page.$eval('#briefsend', (a) => a.getAttribute('href'))
check('the email is addressed to the company and carries the brief', href.startsWith('mailto:info@yalavarti.com?subject=') && decodeURIComponent(href).includes('Project type: Residential') && decodeURIComponent(href).includes('Site: Hyderabad'), decodeURIComponent(href).slice(0, 80))

// The page scrolls and its top bar reacts.
await page.evaluate(() => scrollTo(0, 0))
await sleep(200)
await page.evaluate(() => { scrollTo(0, 1400) })
await sleep(300)
await page.evaluate(() => { scrollTo(0, 2200) })
await sleep(400)
check('the top bar turns solid once the page is scrolled', await page.evaluate(() => document.getElementById('nav').classList.contains('solid')))

// Reading down hides the bar; a little scroll up brings it back.
await page.evaluate(() => scrollTo(0, 0))
await sleep(300)
for (let i = 0; i < 12; i++) { await page.mouse.wheel({ deltaY: 300 }); await sleep(120) }
check('the top bar slides away while reading down', await page.evaluate(() => document.getElementById('nav').classList.contains('hide')))
for (let i = 0; i < 4; i++) { await page.mouse.wheel({ deltaY: -300 }); await sleep(120) }
check('and comes back on scrolling up', await page.evaluate(() => !document.getElementById('nav').classList.contains('hide')))

// An old address still arrives.
await page.goto(BASE + '/index.html', { waitUntil: 'networkidle0' })
check('/index.html still shows the company page or the app, not an error', (await page.title()).length > 0)
await sleep(200)
await done()
