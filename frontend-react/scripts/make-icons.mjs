/**
 * Draws the app icons (public/icons/*.png) from the logo mark, using a
 * headless browser so no image tools are needed.
 *
 *   node scripts/make-icons.mjs
 *
 * BROWSER can point at Edge or Chrome (default: Edge on Windows).
 */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const OUT = join(import.meta.dirname, '..', 'public', 'icons')
mkdirSync(OUT, { recursive: true })

// The Y mark. `pad` shrinks it inside the canvas: a maskable icon must keep
// its artwork inside the middle 80%, because the platform may crop the rest.
const mark = (pad) => `
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="100%" height="100%">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f6a04d"/><stop offset="1" stop-color="#d9541e"/></linearGradient></defs>
    <rect width="32" height="32" rx="${pad ? 0 : 9}" fill="url(#g)"/>
    <g transform="translate(16 16) scale(${pad ? 0.62 : 1}) translate(-16 -16)">
      <path d="M9 9l7 9 7-9M16 18v6" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
  </svg>`

const icons = [
  { file: 'icon-192.png', size: 192, pad: false },
  { file: 'icon-512.png', size: 512, pad: false },
  { file: 'icon-maskable-512.png', size: 512, pad: true },
  { file: 'apple-touch-icon.png', size: 180, pad: true },
]

const browser = await puppeteer.launch({
  executablePath: process.env.BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: 'new',
  args: ['--no-sandbox'],
})
const page = await browser.newPage()
for (const { file, size, pad } of icons) {
  await page.setViewport({ width: size, height: size, deviceScaleFactor: 1 })
  await page.setContent(`<body style="margin:0;background:transparent">${mark(pad)}</body>`)
  await page.screenshot({ path: join(OUT, file), omitBackground: true })
  console.log('wrote', file)
}
await browser.close()
