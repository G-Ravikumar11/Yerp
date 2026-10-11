import type { PayslipDetail } from '@/api/payroll'
import { formatDate } from '@/lib/format'

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
const inr = (n: number) => '&#8377;' + (n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const row = (l: string, v: number) => `<tr><td>${esc(l)}</td><td class="r">${inr(v)}</td></tr>`

const STYLE = `body{font:14px/1.5 system-ui,sans-serif;color:#111;margin:32px auto;max-width:760px}h1{font-size:20px;margin:0}h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;margin:22px 0 6px;color:#555}
table{width:100%;border-collapse:collapse}td{padding:5px 0;border-bottom:1px solid #e5e5e5}.r{text-align:right}.tot td{font-weight:600;border-top:2px solid #111}.head{display:flex;justify-content:space-between;border-bottom:2px solid #111;padding-bottom:12px}
.net{margin-top:18px;padding:12px 14px;background:#f2f2f2;display:flex;justify-content:space-between;font-size:18px;font-weight:700}small{color:#555}`

/** A payslip on its own page, ready to print or save as a PDF from the browser's print dialog. */
export function printPayslip(p: PayslipDetail) {
  const earn: [string, number][] = [['Basic pay', p.basic_salary], [`Overtime${p.overtime_hours ? ` (${p.overtime_hours}h)` : ''}`, p.overtime_pay], ['Bonus', p.bonus], ['Allowances', p.allowances]]
  const ded: [string, number][] = [['Tax', p.tax_amount], ['Insurance', p.insurance], ['Retirement / PF', p.retirement], ['Other deductions', p.other_deductions]]
  if (p.standing_deduction > 0) ded.push(['Standing deduction', p.standing_deduction])
  const e = p.employee
  const html = `<!doctype html><meta charset="utf-8"><title>Payslip ${esc(p.number)}</title><style>${STYLE}</style>
<div class="head"><div><h1>${esc(p.company.name)}</h1><small>${esc(p.company.address)}</small></div><div class="r"><h1>PAYSLIP</h1><small>${esc(p.number)}</small></div></div>
<h2>Employee</h2><p><strong>${esc(e.full_name)}</strong> (${esc(e.employee_id)})<br><small>${esc(e.job_title)}${e.department_name ? ' - ' + esc(e.department_name) : ''}</small><br>
<small>Period ${esc(formatDate(p.period_start))} to ${esc(formatDate(p.period_end))} &middot; pay date ${esc(formatDate(p.pay_date))}</small></p>
<h2>Earnings</h2><table>${earn.map(([l, v]) => row(l, v)).join('')}<tr class="tot"><td>Gross pay</td><td class="r">${inr(p.gross_pay)}</td></tr></table>
<h2>Deductions</h2><table>${ded.map(([l, v]) => row(l, v)).join('')}<tr class="tot"><td>Total deductions</td><td class="r">${inr(p.total_deductions)}</td></tr></table>
<div class="net"><span>Net pay</span><span>${inr(p.net_pay)}</span></div>
${e.bank_account ? `<p><small>Paid to ${esc(e.bank_name)} ${esc(e.bank_account)}</small></p>` : ''}${p.notes ? `<p>${esc(p.notes)}</p>` : ''}
<script>addEventListener('load',()=>setTimeout(()=>print(),200))</script>`
  const w = window.open('', '_blank')
  if (!w) return
  w.document.write(html)
  w.document.close()
}
