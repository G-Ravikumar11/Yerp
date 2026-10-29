import type { PayslipDetail } from '@/api/payroll'

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
const amt = (n: number) => String(Math.round((n || 0) * 100) / 100)

const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
const below100 = (n: number) => (n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? ' ' + ONES[n % 10] : ''))
const below1000 = (n: number) => (n >= 100 ? ONES[Math.floor(n / 100)] + ' Hundred' + (n % 100 ? ' ' + below100(n % 100) : '') : below100(n))

/** Rupees in words the Indian way (thousand, lakh, crore): 61800 is "Rupees Sixty One Thousand Eight Hundred Only". */
function rupeesInWords(value: number): string {
  let n = Math.round(Math.abs(value || 0))
  if (n === 0) return 'Rupees Zero Only'
  const parts: string[] = []
  for (const [size, name] of [[10000000, 'Crore'], [100000, 'Lakh'], [1000, 'Thousand']] as const) {
    if (n >= size) { parts.push(below1000(Math.floor(n / size)) + ' ' + name); n %= size }
  }
  if (n) parts.push(below1000(n))
  return 'Rupees ' + parts.join(' ') + ' Only'
}

const STYLE = `*{box-sizing:border-box}body{font:13px/1.35 Calibri,Arial,sans-serif;color:#000;margin:0;padding:24px 28px;background:#fff}
.logo{height:56px;margin-bottom:14px}.co{text-align:center;font-weight:700;font-size:14px;margin:6px 0}.addr{text-align:center;font-weight:700;margin:10px 0 16px}.title{text-align:center;font-weight:700;margin:12px 0 10px}
table{width:100%;border-collapse:collapse}td{border:1px solid #000;padding:2px 5px;height:21px}.r{text-align:right}.h td{background:#c0c0c0}.b{font-weight:700}
.net{margin:18px 0 0 8px;font-weight:700}.net span{display:inline-block;min-width:60px}.words{margin:6px 0 0 70px;font-size:11px;font-weight:700}.note{margin:36px 0 0;font-family:'Times New Roman',serif;font-size:13px}
.foot{margin-top:60px;padding-top:6px;text-align:center;color:#555;font-size:11px}`

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monthYear = (iso: string) => {
  const d = new Date(iso + 'T00:00')
  return isNaN(d.getTime()) ? '' : `${MONTHS[d.getMonth()]}-${String(d.getFullYear()).slice(2)}`
}
const joined = (iso: string) => {
  const d = new Date(iso + 'T00:00')
  return isNaN(d.getTime()) ? '' : `${String(d.getDate()).padStart(2, '0')}-${MONTHS[d.getMonth()]}-${d.getFullYear()}`
}

/** The payslip as one page: employee details, earnings beside deductions, net pay in figures and words. */
export function payslipHtml(p: PayslipDetail, { autoPrint = false } = {}): string {
  const e = p.employee
  const c = p.company
  // Every column of the sheet. A head the application holds no figure for is left empty, for the office to complete.
  const earn: [string, number | null][] = [['Basic', p.basic_salary], ['HRA', null], ['Site Allowance', null], ['Special Allownace', null], ['Mobile Allowance', null], ['Transport Allowance', null], ['Other Allowance', p.allowances]]
  if (p.overtime_pay) earn.push([`Overtime${p.overtime_hours ? ` (${p.overtime_hours}h)` : ''}`, p.overtime_pay])
  if (p.bonus) earn.push(['Bonus', p.bonus])
  const ded: [string, number | null][] = [['PF', p.retirement], ['ESI', p.insurance], ['Prof Tax', null], ['Salary Advance', null], ['TDS Deduction', p.tax_amount], ['Loss Of Pay', null], ['Other Deductions', p.other_deductions]]
  if (p.standing_deduction > 0) ded.push(['Standing Deduction', p.standing_deduction])
  const rows = Math.max(earn.length, ded.length, 4)
  const lines = Array.from({ length: rows }, (_, i) => `<tr><td colspan="2">${esc(earn[i]?.[0] ?? '')}</td><td class="r">${earn[i]?.[1] != null ? amt(earn[i][1] as number) : ''}</td><td colspan="2">${esc(ded[i]?.[0] ?? '')}</td><td class="r">${ded[i]?.[1] != null ? amt(ded[i][1] as number) : ''}</td></tr>`).join('')
  const info = (l: string, v: unknown, l2: string, v2: unknown) => `<tr><td>${l}</td><td colspan="2">${esc(v)}</td><td>${l2}</td><td colspan="2">${esc(v2)}</td></tr>`
  const contact = [c.address, [c.phone && `Phone : ${c.phone}`, c.email && `E-mail : ${c.email}`].filter(Boolean).join(', ')].filter(Boolean)
  return `<!doctype html><meta charset="utf-8"><title>Payslip ${esc(p.number)}</title><style>${STYLE}</style>
${c.logo_url ? `<img class="logo" src="${esc(c.logo_url)}" alt="">` : ''}
<div class="co">${esc(c.name)}</div>${c.address ? `<div class="addr">${esc(c.address)}</div>` : ''}
<div class="title">Payslip For The Month of ${esc(monthYear(p.period_end || p.period_start))}</div>
<table>
${info('Employee No.', e.employee_id, 'Location .', e.work_location)}
${info('Name.', e.full_name, 'Department.', e.department_name)}
${info('Bank Name.', e.bank_name, 'Designation.', e.job_title)}
${info('Bank Acc.No.', e.bank_account, 'Total Days.', p.days.total || '')}
${info('Father Name.', '', 'LOP .', '')}
${info('Salary Per Month.', amt(p.gross_pay), 'Balance Leaves.', p.days.balance_leaves)}
${info('DOJ.', joined(e.start_date), 'Work Days.', p.days.work || '')}
${info('Aadhar No.', e.aadhaar_masked, 'Effective Work days.', p.days.work || '')}
${info('UAN No', e.uan_no, 'ESI No', e.esi_no)}
<tr class="h"><td colspan="3">Earnings</td><td colspan="3">Deductions</td></tr>
${lines}
<tr class="b"><td colspan="2">Total Earnings : Rs.</td><td class="r">${amt(p.gross_pay)}</td><td colspan="2">Total Deductions : Rs.</td><td class="r">${amt(p.total_deductions)}</td></tr>
</table>
<div class="net">Net Pay : &nbsp;&nbsp;&nbsp;<span>Rs.</span>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;${amt(p.net_pay)}</div>
<div class="words">In Words : &nbsp;${esc(rupeesInWords(p.net_pay))}</div>
${p.notes ? `<p>${esc(p.notes)}</p>` : ''}
<p class="note">** This is computer generated payslip no need any signature</p>
${contact.length ? `<div class="foot">${contact.map(esc).join('<br>')}</div>` : ''}
${autoPrint ? "<script>addEventListener('load',()=>setTimeout(()=>print(),200))</script>" : ''}`
}

/** A payslip on its own page, ready to print or save as a PDF from the browser's print dialog. */
export function printPayslip(p: PayslipDetail) {
  const w = window.open('', '_blank')
  if (!w) return
  w.document.write(payslipHtml(p, { autoPrint: true }))
  w.document.close()
}
