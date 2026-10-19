import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button, Modal } from '@/components/ui'
import { PictureField } from '@/components/data/PictureField'
import { saveLogo, settingsKeys } from '@/api/settings'
import type { Activity, Schedule } from '@/api/schedule'
import { today } from '@/lib/format'
import { useAction } from '@/lib/mutate'

const DAY = 86400000
const at = (iso: string) => Math.round(new Date(iso + 'T00:00:00').getTime() / DAY)
const dmy = (iso?: string) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
const stamp = () => new Date().toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

// A4 portrait is 210 x 297 mm. The 10 mm margin is padding on the report rather than the @page margin: a page margin is
// where the browser prints its own date, title and address, so a zero page margin is what keeps those off the sheet.
const MARGIN = 10
const PAGE_W = 210
const PAGE_H = 297
const CONTENT_W = PAGE_W - 2 * MARGIN
const CONTENT_H = PAGE_H - 2 * MARGIN
const MM = 96 / 25.4
/** Below this the writing is too small to read on one sheet; the report then runs to more pages, with its header repeated. */
const MIN_SCALE = 0.8
/** The report is already laid out to the full width of the sheet; enlarging it only squeezes the columns, so it is never enlarged. */
const MAX_SCALE = 1

/**
 * How the report looks. Scoped to the report, which is not on screen, so it can always be present. The layout of the sheet
 * itself (the page size, hiding the application, showing the report) is added only while printing, in PAGE_CSS.
 */
const REPORT_CSS = `
#chart-print-root { display: none; color: #111; background: #fff; font: 9.5pt/1.3 "Segoe UI", Arial, Helvetica, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
#chart-print-root * { box-sizing: border-box; }
#chart-print-root .rp-sheet { padding: ${MARGIN}mm; width: ${PAGE_W}mm; background: #fff; }
#chart-print-root .rp-page { width: ${CONTENT_W}mm; }
#chart-print-root .rp-head { display: flex; justify-content: space-between; align-items: center; gap: 12mm; padding-bottom: 3mm; border-bottom: 1.5pt solid #111; margin-bottom: 3mm; }
#chart-print-root .rp-brand { display: flex; align-items: center; gap: 4mm; min-width: 0; }
#chart-print-root .rp-logo { height: 16mm; max-width: 55mm; object-fit: contain; display: block; }
#chart-print-root .rp-co { font-size: 13pt; font-weight: 700; line-height: 1.15; }
#chart-print-root .rp-sub { font-size: 8pt; color: #444; }
#chart-print-root .rp-title { text-align: right; flex: none; }
#chart-print-root .rp-title h1 { margin: 0; font-size: 19pt; line-height: 1.1; letter-spacing: .02em; }
#chart-print-root .rp-title p { margin: .8mm 0 0; font-size: 8pt; color: #444; }
#chart-print-root .rp-meta { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.2mm 6mm; margin: 0 0 2.5mm; padding: 2mm 3mm; border: .75pt solid #999; }
#chart-print-root .rp-meta dt { font-size: 7pt; text-transform: uppercase; letter-spacing: .05em; color: #555; }
#chart-print-root .rp-meta dd { margin: 0; font-weight: 600; font-size: 9pt; overflow-wrap: anywhere; }
#chart-print-root .rp-sum { display: flex; gap: 8mm; margin: 0 0 2mm; font-size: 8.5pt; }
#chart-print-root table { width: 100%; border-collapse: collapse; table-layout: fixed; }
#chart-print-root thead { display: table-header-group; }
#chart-print-root tr { break-inside: avoid; page-break-inside: avoid; }
#chart-print-root th, #chart-print-root td { border: .6pt solid #777; padding: 1.1mm 1.6mm; vertical-align: middle; text-align: left; overflow-wrap: anywhere; }
#chart-print-root th { background: #e9e9e9; font-size: 7.5pt; text-transform: uppercase; letter-spacing: .03em; }
#chart-print-root tr.rp-run, #chart-print-root tfoot { display: none; }
#chart-print-root .rp-page.multi tr.rp-run { display: table-row; }
#chart-print-root .rp-page.multi tfoot { display: table-footer-group; }
#chart-print-root tr.rp-run th { background: #fff; border: 0; border-bottom: .75pt solid #111; padding: ${MARGIN - 1}mm 0 1.5mm; text-transform: none; letter-spacing: 0; font-size: 8.5pt; font-weight: 600; }
#chart-print-root .rp-run img { height: 7mm; vertical-align: middle; margin-right: 3mm; }
#chart-print-root tfoot td { border: 0; height: ${MARGIN}mm; padding: 0; }
#chart-print-root .num { text-align: right; white-space: nowrap; }
#chart-print-root .code { font-family: Consolas, monospace; font-size: 8pt; }
#chart-print-root .late td { background: #fbeaea; }
#chart-print-root td.st { overflow-wrap: normal; word-break: normal; }
#chart-print-root .late .st { color: #a40000; font-weight: 700; }
#chart-print-root .ms td:nth-child(2) { font-weight: 700; }
#chart-print-root .small { font-size: 7pt; color: #555; line-height: 1.2; }
#chart-print-root .tl { position: relative; padding: 0; }
#chart-print-root th.tl-h { position: relative; padding: 0; height: 6mm; font-size: 6.5pt; overflow: hidden; }
#chart-print-root .tl-h span { position: absolute; top: 1.4mm; transform: translateX(2px); white-space: nowrap; font-weight: 600; }
#chart-print-root .bar { position: absolute; top: 50%; margin-top: -1.6mm; height: 3.2mm; background: #d6d6d6; border: .5pt solid #666; }
#chart-print-root .bar i { display: block; height: 100%; background: #1a1a1a; }
#chart-print-root .bar.overdue i { background: #b00000; }
#chart-print-root .bar.done i { background: #2d7a3a; }
#chart-print-root .dia { position: absolute; top: 50%; margin-top: -1.8mm; width: 3.6mm; height: 3.6mm; background: #1a1a1a; transform: rotate(45deg); }
#chart-print-root .dia.done { background: #2d7a3a; } #chart-print-root .dia.overdue { background: #b00000; }
#chart-print-root .today { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1pt dashed #b00000; }
#chart-print-root .rp-key { margin: 2mm 0 0; font-size: 7pt; color: #444; }
#chart-print-root .rp-sign { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12mm; margin-top: 9mm; break-inside: avoid; }
#chart-print-root .rp-sign div { border-top: .75pt solid #111; padding-top: 1.2mm; font-size: 8pt; color: #333; }
/* A long programme: tighter rows, so more fits at a size that can still be read. */
#chart-print-root .rp-page.compact { font-size: 8pt; }
#chart-print-root .rp-page.compact th, #chart-print-root .rp-page.compact td { padding: .5mm 1.2mm; }
#chart-print-root .rp-page.compact .small { display: none; }
#chart-print-root .rp-page.compact .rp-logo { height: 12mm; }
#chart-print-root .rp-page.compact .rp-meta { padding: 1.2mm 3mm; margin-bottom: 1.5mm; }
#chart-print-root .rp-page.compact .rp-sign { margin-top: 5mm; }
`

/** Only while printing: the sheet, and the application out of the way. Under @media print, so nothing shows on screen. */
const PAGE_CSS = `
@page { size: A4 portrait; margin: 0; }
@media print {
  html, body { background: #fff !important; margin: 0 !important; padding: 0 !important; height: auto !important; }
  body.printing-chart > *:not(#chart-print-root) { display: none !important; }
  body.printing-chart #chart-print-root { display: block !important; position: static !important; }
  body.printing-chart #chart-print-root.single { height: ${PAGE_H - 1}mm; overflow: hidden; }
}
`

/** The logo must have arrived before the print dialog opens, or the sheet prints a blank where it should be. */
const loaded = (src: string) => new Promise<void>((resolve) => {
  if (!src) return resolve()
  const img = new Image()
  img.src = src
  if (img.complete) return resolve()
  img.onload = () => resolve()
  img.onerror = () => resolve()
  window.setTimeout(() => resolve(), 1200)
})

/** Size the report to the sheet: measured as it will be laid out, then scaled so that all of it is on one A4 page. */
function fitReport(): { scale: number; pages: number } {
  const root = document.getElementById('chart-print-root')
  const page = root?.querySelector<HTMLElement>('.rp-page')
  if (!root || !page) return { scale: 1, pages: 1 }
  const measure = (scale = 1) => {
    root.style.cssText = 'display:block;position:absolute;left:-99999px;top:0;visibility:hidden;'
    page.style.zoom = ''
    page.style.width = scale === 1 ? '' : `${CONTENT_W / scale}mm`
    const h = page.scrollHeight
    root.style.cssText = ''
    return h
  }
  page.classList.remove('compact', 'multi')
  root.classList.add('single')
  const room = CONTENT_H * MM * 0.985
  let h = measure()
  if (h > room) { page.classList.add('compact'); h = measure() }
  let scale = Math.min(MAX_SCALE, room / h)
  // Enlarged, the report is laid out narrower before it is zoomed, so rows wrap more: measure it that way, and settle.
  for (let i = 0; scale > 1 && i < 5; i++) {
    const again = measure(scale)
    if (again * scale <= room) break
    scale = Math.max(1, room / again)
  }
  if (scale > 1) scale = Math.max(1, scale * 0.99)
  let pages = 1
  if (scale < MIN_SCALE) {
    // Too much for one sheet at a size anyone could read: keep it legible, and let it run on with its header repeated.
    page.classList.add('multi')
    root.classList.remove('single')
    scale = MIN_SCALE
    pages = Math.ceil((h * MIN_SCALE) / (CONTENT_H * MM))
  }
  // zoom scales the layout as well, so the width given is what it will be before the scaling: the sheet's own width after.
  page.style.zoom = String(scale)
  page.style.width = `${CONTENT_W / scale}mm`
  return { scale, pages }
}

/** The sheet, for a document that holds nothing but the report. */
const SHEET_CSS = `
@page { size: A4 portrait; margin: 0; }
html, body { margin: 0; padding: 0; background: #fff; }
#chart-print-root { display: block !important; }
#chart-print-root.single { height: ${PAGE_H - 1}mm; overflow: hidden; }
`

/** Every picture in a document loaded - a logo still arriving prints as a blank. */
const picturesIn = (doc: Document) => Promise.all([...doc.images].map((img) => (img.complete ? null : new Promise<void>((r) => { img.onload = img.onerror = () => r(); window.setTimeout(r, 1200) }))))

/**
 * Print the chart. The report is fitted to the sheet, then printed from a document of its own - a hidden frame holding the
 * report and the A4 portrait rule and nothing else. None of the application's own layout is in that document to be
 * printed or to stretch the page, so what the print dialog is given is one A4 portrait sheet, and Save as PDF gives the same.
 */
export async function printChart(logo: string) {
  await loaded(logo)
  const fit = fitReport()
  const root = document.getElementById('chart-print-root')
  if (!root) return fit
  document.getElementById('chart-print-frame')?.remove()
  const frame = document.createElement('iframe')
  frame.id = 'chart-print-frame'
  frame.title = 'Project Chart print'
  frame.setAttribute('aria-hidden', 'true')
  // Off the screen but laid out at the size of the sheet, so the browser measures it as it will print.
  frame.style.cssText = `position:fixed;left:-10000px;top:0;width:${PAGE_W}mm;height:${PAGE_H}mm;border:0;visibility:hidden;`
  document.body.appendChild(frame)
  const doc = frame.contentDocument
  const win = frame.contentWindow
  if (!doc || !win) return fit
  doc.open()
  doc.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Project Chart</title><base href="${location.origin}/"><style>${SHEET_CSS}</style></head><body><div id="chart-print-root" class="${root.className}">${root.innerHTML}</div></body></html>`)
  doc.close()
  await picturesIn(doc)
  await new Promise((r) => requestAnimationFrame(() => r(null)))
  const cleanup = () => window.setTimeout(() => frame.remove(), 1000)
  win.addEventListener('afterprint', cleanup)
  win.focus()
  win.print()
  return fit
}

/**
 * Ctrl+P on the chart prints the same report, not the screen: the page switches to the report as the dialog opens, and back after.
 */
function usePrintShortcut() {
  useEffect(() => {
    let style: HTMLStyleElement | null = null
    const before = () => {
      fitReport()
      style = document.createElement('style')
      style.id = 'chart-print-style'
      style.textContent = PAGE_CSS
      document.head.appendChild(style)
      document.body.classList.add('printing-chart')
    }
    const after = () => {
      document.body.classList.remove('printing-chart')
      style?.remove()
      style = null
    }
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => { window.removeEventListener('beforeprint', before); window.removeEventListener('afterprint', after); after() }
  }, [])
}

/** The report itself: in the page, not shown, and printed from. Real text and drawn shapes - never a picture of the screen. */
export function PrintReport({ schedule, company }: { schedule: Schedule; company: { name: string; address: string; gstin: string; logo_url: string } }) {
  usePrintShortcut()
  useEffect(() => { if (company.logo_url) void loaded(company.logo_url) }, [company.logo_url])
  const job = schedule.job
  const rows = schedule.activities
  const s = schedule.summary
  const dates = rows.flatMap((a) => [a.planned_start, a.planned_finish, a.forecast_finish]).filter(Boolean).map(at)
  const todayN = at(today())
  const t0 = dates.length ? Math.min(...dates) : todayN
  const t1 = dates.length ? Math.max(...dates, todayN) : todayN
  const span = Math.max(1, t1 - t0 + 1)
  const pct = (n: number) => `${(((n - t0) / span) * 100).toFixed(2)}%`
  const months: { n: number; label: string }[] = []
  for (let n = t0; n <= t1; n++) if (n === t0 || new Date(n * DAY).getUTCDate() === 1) months.push({ n, label: new Date(n * DAY).toLocaleDateString('en-GB', { timeZone: 'UTC', month: 'short', year: '2-digit' }) })
  // A label that starts too near the right-hand edge would run past it: leave those off.
  const fitting = months.filter((m) => (m.n - t0) / span < 0.9)
  const sparse = fitting.length > 5 ? fitting.filter((_, i) => i % Math.ceil(fitting.length / 5) === 0) : fitting
  const days = (a: Activity) => (a.is_milestone ? '-' : String(at(a.planned_finish) - at(a.planned_start) + 1))
  const root = document.getElementById('chart-print-root') ?? Object.assign(document.createElement('div'), { id: 'chart-print-root' })
  if (!root.parentElement) document.body.appendChild(root)
  return createPortal(
    <div className="rp-sheet">
      <style>{REPORT_CSS}</style>
      <div className="rp-page">
        <header className="rp-head">
          <div className="rp-brand">
            {company.logo_url && <img className="rp-logo" src={company.logo_url} alt={`${company.name} logo`} />}
            <div><div className="rp-co">{company.name}</div>{company.address && <div className="rp-sub">{company.address}</div>}{company.gstin && <div className="rp-sub">GSTIN {company.gstin}</div>}</div>
          </div>
          <div className="rp-title"><h1>Project Chart</h1><p>Printed {stamp()}</p></div>
        </header>
        <dl className="rp-meta">
          <div><dt>Project</dt><dd>{job ? `${job.number} - ${job.name}` : '-'}</dd></div>
          <div><dt>Client</dt><dd>{job?.customer_name || '-'}</dd></div>
          <div><dt>Site</dt><dd>{job?.site_address || '-'}</dd></div>
          <div><dt>Status</dt><dd>{job?.status || '-'}</dd></div>
          <div><dt>Programme start</dt><dd>{dmy(s.start)}</dd></div>
          <div><dt>Planned finish</dt><dd>{dmy(s.end)}{s.slip_days > 0 && ` (forecast ${dmy(s.forecast_finish)})`}</dd></div>
          <div><dt>Duration</dt><dd>{s.duration_days ? `${s.duration_days} days` : '-'}</dd></div>
          <div><dt>Progress planned / actual</dt><dd>{s.planned_percent}% / {s.actual_percent}%</dd></div>
        </dl>
        <p className="rp-sum"><span><b>{s.activities}</b> activities</span><span><b>{s.done}</b> completed</span><span><b>{s.overdue ?? 0}</b> overdue</span><span><b>{s.milestones_done ?? 0}</b> of <b>{s.milestones ?? 0}</b> milestones reached</span></p>
        <table>
          <colgroup><col style={{ width: '7%' }} /><col style={{ width: '20%' }} /><col style={{ width: '10%' }} /><col style={{ width: '9%' }} /><col style={{ width: '9%' }} /><col style={{ width: '5%' }} /><col style={{ width: '6.5%' }} /><col style={{ width: '11.5%' }} /><col style={{ width: '22%' }} /></colgroup>
          <thead>
            <tr className="rp-run"><th colSpan={9}>{company.logo_url && <img src={company.logo_url} alt="" />}{company.name} - Project Chart - {job ? `${job.number} ${job.name}` : ''}</th></tr>
            <tr>
              <th>Code</th><th>Activity</th><th>Assigned to</th><th>Start</th><th>Finish</th><th className="num">Days</th><th className="num">Done</th><th>Status</th>
              <th className="tl-h">{sparse.map((m) => <span key={m.n} style={{ left: pct(m.n) }}>{m.label}</span>)}</th>
            </tr>
          </thead>
          <tfoot><tr><td colSpan={9} /></tr></tfoot>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={9}>No activities have been entered for this project.</td></tr>}
            {rows.map((a) => {
              const st = a.status || 'Not Started'
              const cls = a.overdue ? 'overdue' : st === 'Completed' ? 'done' : ''
              return (
                <tr key={a.id} className={`${a.overdue ? 'late' : ''} ${a.is_milestone ? 'ms' : ''}`}>
                  <td className="code">{a.code}</td>
                  <td>{a.is_milestone && '◆ '}{a.name}{a.predecessor_code && <div className="small">after {a.predecessor_code}</div>}{a.notes && <div className="small">{a.notes}</div>}</td>
                  <td>{a.assigned_to || '-'}</td>
                  <td>{dmy(a.planned_start)}</td>
                  <td>{dmy(a.planned_finish)}</td>
                  <td className="num">{days(a)}</td>
                  <td className="num">{Math.round(a.actual_percent)}%<div className="small">plan {Math.round(a.planned_percent)}%</div></td>
                  <td className="st">{st}{a.overdue && <div>{a.days_late} day{a.days_late === 1 ? '' : 's'} overdue</div>}</td>
                  <td className="tl">
                    {todayN >= t0 && todayN <= t1 && <span className="today" style={{ left: pct(todayN) }} />}
                    {a.is_milestone
                      ? <span className={`dia ${cls}`} style={{ left: `calc(clamp(2.6mm, ${pct(at(a.planned_finish))}, 100% - 2.6mm) - 1.8mm)` }} />
                      : <span className={`bar ${cls}`} style={{ left: pct(at(a.planned_start)), width: `${(((at(a.planned_finish) - at(a.planned_start) + 1) / span) * 100).toFixed(2)}%` }}><i style={{ width: `${Math.min(100, a.actual_percent)}%` }} /></span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="rp-key">Bars run from planned start to planned finish and are filled to actual progress. ◆ marks a milestone. The dashed line is the print date. Overdue activities are shaded and named in the Status column.</p>
        <div className="rp-sign"><div>Prepared by</div><div>Checked by</div><div>Approved by</div></div>
      </div>
    </div>,
    root,
  )
}

/** Offered when the company has no logo yet: add one here, or print without. The logo is the company's own - saved for every document. */
export function LogoPrintModal({ open, onClose, onPrint }: { open: boolean; onClose: () => void; onPrint: (logo: string) => void }) {
  const [pic, setPic] = useState('')
  const save = useAction(() => saveLogo(pic), { invalidate: [settingsKeys.all], success: 'Logo saved for every document.', onSuccess: () => onPrint(pic) })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Add your company logo?" description="The printed report carries the company logo at the top. None has been added yet.">
      {open && (
        <div>
          <PictureField label="Logo" value={pic} onChange={setPic} hint="PNG or JPEG. It is shrunk to fit and kept in the company settings." />
          <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
            {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="outline" onClick={() => onPrint('')}>Print without a logo</Button>
            <Button loading={save.isPending} disabled={!pic} onClick={() => save.mutate()}>Save the logo and print</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
