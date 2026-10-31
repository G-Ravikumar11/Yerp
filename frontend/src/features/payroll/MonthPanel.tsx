import { useEffect, useState } from 'react'
import { Download, Lock, LockOpen } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Select } from '@/components/ui'
import { EXPORTS, exportUrl, monthTone, moveMonth, payKeys, reopenMonth, usePayrollMonths, type ExportKind, type MonthStatus, type PayrollMonth } from '@/api/payroll'
import { apiUrl } from '@/lib/api'
import { fileNameFor } from '@/lib/download'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

const label = (month: string) => new Date(`${month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

/** The next step from each status, what its button says, and what to warn about before taking it. */
const NEXT: Partial<Record<MonthStatus, { action: 'approve' | 'pay' | 'lock'; button: string; title: string; warn: string }>> = {
  Draft: { action: 'approve', button: 'Approve month', title: 'Approve', warn: "Staff can see their payslips once the month is approved. If emailing on approval is switched on, everybody's payslip goes out now." },
  Approved: { action: 'pay', button: 'Mark month paid', title: 'Mark as paid', warn: 'Every payslip in the month is marked paid.' },
  Paid: { action: 'lock', button: 'Lock month', title: 'Lock', warn: 'Nothing in a locked month can be created, changed or deleted until the Master reopens it.' },
}

/**
 * Fetches an export and saves it. Fetched rather than linked so a refusal (somebody with no IFSC, say) is read and shown
 * instead of opening as a page of JSON; saved through a link the phone app already knows how to hand to its share sheet.
 * Answers with the server's reason when it refused.
 */
async function fetchExport(url: string): Promise<{ ok: true } | { ok: false; status: number; detail: string }> {
  const res = await fetch(apiUrl(url), { credentials: 'include' })
  if (!res.ok) {
    let detail = 'That file could not be made.'
    try { detail = String(((await res.json()) as { detail?: unknown }).detail ?? detail) } catch { /* not JSON */ }
    return { ok: false, status: res.status, detail }
  }
  const href = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = href
  a.download = fileNameFor(null, res.headers.get('content-disposition'), url)
  a.click()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
  const left = Number(res.headers.get('X-Rows-Left-Out') || 0)
  if (left > 0) toast.info(`${left} ${left === 1 ? 'person was' : 'people were'} left out of the file.`)
  return { ok: true }
}

/** Where a month's payroll stands, the button for its next step, and its bank and statutory files. */
export function MonthPanel() {
  const q = usePayrollMonths()
  const { isOwner } = useSession()
  const months = q.data ?? []
  const [month, setMonth] = useState('')
  useEffect(() => { if (!month && months.length) setMonth(months[0].month) }, [months, month])
  const m: PayrollMonth | undefined = months.find((x) => x.month === month)
  const [confirming, setConfirming] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [refused, setRefused] = useState<{ kind: ExportKind; detail: string } | null>(null)
  const [busy, setBusy] = useState<ExportKind | null>(null)

  const next = m ? NEXT[m.status] : undefined
  const move = useAction(() => moveMonth(next!.action, month), {
    invalidate: [payKeys.all], success: (r) => r.message || 'Saved', onSuccess: (r) => { setConfirming(false); if (r.emails?.skipped?.length) toast.info(`No email address for: ${r.emails.skipped.join(', ')}`) },
  })
  const reopen = useAction((reason: string) => reopenMonth(month, reason), {
    invalidate: [payKeys.all], success: (r) => r.message || 'Reopened', onSuccess: () => setReopening(false),
  })

  const download = async (kind: ExportKind, allowIncomplete = false) => {
    setBusy(kind)
    try {
      const r = await fetchExport(exportUrl(kind, month, allowIncomplete))
      if (r.ok) setRefused(null)
      // Somebody's details are missing: say who, and offer the file without them.
      else if (r.status === 400 && /cannot go in the file/.test(r.detail)) setRefused({ kind, detail: r.detail })
      else toast.error(r.detail)
    } catch {
      toast.error('That file could not be downloaded. Check the connection and try again.')
    } finally {
      setBusy(null)
    }
  }

  if (!months.length) return null
  return (
    <section aria-label="Month" className="mb-4 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-44"><Select aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} options={months.map((x) => ({ value: x.month, label: label(x.month) }))} /></div>
        {m && <Badge tone={monthTone(m.status)} dot>{m.status === 'Locked' ? <><Lock className="size-3" /> Locked</> : m.status}</Badge>}
        {m && <span className="text-[13px] text-muted-foreground">{m.payslips ?? 0} payslip{m.payslips === 1 ? '' : 's'}, net {formatINR(m.net_pay ?? 0)}</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          {next && <Button size="sm" onClick={() => setConfirming(true)}>{next.button}</Button>}
          {m?.status === 'Locked' && isOwner && <Button size="sm" variant="outline" onClick={() => setReopening(true)}><LockOpen /> Reopen month</Button>}
        </div>
      </div>
      {m?.status === 'Locked' && <p className="mt-2 text-[13px] text-muted-foreground">Locked{m.locked_by ? ` by ${m.locked_by}` : ''}{m.locked_at ? ` on ${m.locked_at.slice(0, 10)}` : ''}. {isOwner ? '' : 'Only the Master can reopen it.'}</p>}
      {m?.reopen_reason && m.status !== 'Locked' && <p className="mt-2 text-[13px] text-muted-foreground">Reopened by {m.reopened_by} on {m.reopened_at.slice(0, 10)}: {m.reopen_reason}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <span className="mr-1 text-[13px] text-muted-foreground">Files for {month ? label(month) : 'the month'}:</span>
        {EXPORTS.map((x) => <Button key={x.kind} size="sm" variant="outline" loading={busy === x.kind} disabled={!month || !!busy} onClick={() => download(x.kind)}><Download /> {x.label}</Button>)}
      </div>
      {refused && (
        <div role="alert" className="mt-3 rounded-md bg-warning-soft p-3 text-[13px] text-warning">
          <p>{refused.detail}</p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" loading={busy === refused.kind} onClick={() => download(refused.kind, true)}>Download without them</Button>
            <Button size="sm" variant="ghost" onClick={() => setRefused(null)}>Close</Button>
          </div>
        </div>
      )}
      {next && <ConfirmDialog open={confirming} onOpenChange={setConfirming} title={`${next.title} ${label(month)}?`} description={next.warn} confirmLabel={next.button} loading={move.isPending} onConfirm={() => move.mutate()} />}
      <ConfirmDialog open={reopening} onOpenChange={setReopening} title={`Reopen ${month ? label(month) : 'the month'}?`} description="It goes back to Paid, so its payslips can be corrected. The reason is kept in the audit log." confirmLabel="Reopen month" tone="danger"
        reason={{ label: 'Why is it being reopened?', placeholder: 'For example: wrong PF on two payslips', required: true }} loading={reopen.isPending} onConfirm={(reason) => reopen.mutate(reason)} />
    </section>
  )
}
