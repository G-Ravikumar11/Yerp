import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useAction } from '@/lib/mutate'
import { storePost, storePut } from '@/api/store'
import { num, outwardKeys, today, useDocs, useOutstanding, type Doc, type OutstandingLines } from './api'

type Line = OutstandingLines['lines'][number]

/** Material back from site: choose a posted issue, then say how much of each line came back and how much was lost or damaged. */
export default function ReturnForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const issues = useDocs('issue', { status: 'POSTED', store_id: 0, q: '' })
  const [issueId, setIssueId] = useState(doc?.issue_id ?? Number(params.get('issue') || 0))
  const [date, setDate] = useState(doc?.date || today())
  const [remarks, setRemarks] = useState(doc?.remarks ?? '')
  const lines = useOutstanding(issueId)
  const [back, setBack] = useState<Record<number, string>>(() => Object.fromEntries((doc?.lines ?? []).map((l) => [l.issue_line_id, Number(l.qty_returned) ? String(Number(l.qty_returned)) : ''])))
  const [lost, setLost] = useState<Record<number, string>>(() => Object.fromEntries((doc?.lines ?? []).map((l) => [l.issue_line_id, Number(l.qty_lost) ? String(Number(l.qty_lost)) : ''])))
  const [why, setWhy] = useState<Record<number, string>>(() => Object.fromEntries((doc?.lines ?? []).map((l) => [l.issue_line_id, l.reason ?? ''])))
  const picked = (lines.data?.lines ?? []).filter((l) => Number(back[l.issue_line_id]) > 0 || Number(lost[l.issue_line_id]) > 0)
  const save = useAction(
    () => {
      const body = { issue_id: issueId, return_date: date, remarks, lines: picked.map((l) => ({ issue_line_id: l.issue_line_id, qty_returned: back[l.issue_line_id] ?? '', qty_lost: lost[l.issue_line_id] ?? '', uom: l.base_uom, reason: why[l.issue_line_id] ?? '' })) }
      return doc ? storePut<Doc>('outward', `/returns/${doc.id}`, body) : storePost<Doc>('outward', '/returns', body)
    },
    { invalidate: [[...outwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/outward/returns/${d.id}`) },
  )
  const needsReason = picked.some((l) => Number(lost[l.issue_line_id]) > 0 && !(why[l.issue_line_id] ?? '').trim())
  const columns: TableColumn<Line>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
    { id: 'iss', header: 'Issued', align: 'right', width: '7rem', hideBelow: 'sm', cell: (l) => `${num(l.issued)} ${l.base_uom}` },
    { id: 'out', header: 'Still out', align: 'right', width: '7rem', cell: (l) => `${num(l.outstanding)} ${l.base_uom}` },
    { id: 'back', header: 'Came back', width: '8rem', cell: (l) => <Input aria-label={`Quantity of ${l.item_name} that came back`} inputMode="decimal" className="text-right" placeholder="0" value={back[l.issue_line_id] ?? ''} onChange={(e) => setBack((q) => ({ ...q, [l.issue_line_id]: e.target.value }))} /> },
    { id: 'lost', header: 'Lost / damaged', width: '8rem', cell: (l) => (l.returnable ? <Input aria-label={`Quantity of ${l.item_name} lost or damaged`} inputMode="decimal" className="text-right" placeholder="0" value={lost[l.issue_line_id] ?? ''} onChange={(e) => setLost((q) => ({ ...q, [l.issue_line_id]: e.target.value }))} /> : <span className="text-xs text-muted-foreground">Consumable</span>) },
    { id: 'why', header: 'Reason', width: '12rem', cell: (l) => <Input aria-label={`Reason for ${l.item_name}`} placeholder={Number(lost[l.issue_line_id]) > 0 ? 'Required' : ''} value={why[l.issue_line_id] ?? ''} onChange={(e) => setWhy((q) => ({ ...q, [l.issue_line_id]: e.target.value }))} /> },
  ]
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (issueId && picked.length && !needsReason) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Issue it came from" htmlFor="rt-issue" hint="Only posted issues can have material returned.">
          <Select id="rt-issue" value={issueId || ''} placeholder="Choose an issue" disabled={!!doc} onChange={(e) => { setIssueId(Number(e.target.value) || 0); setBack({}); setLost({}); setWhy({}) }}
            options={(issues.data?.items ?? []).map((d) => ({ value: d.id, label: `${d.number} - ${d.holder_name || d.project || 'site use'}` }))} />
        </Field>
        <Field label="Return date" htmlFor="rt-date"><Input id="rt-date" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="rt-rem"><Textarea id="rt-rem" rows={1} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
      </div>
      {issueId > 0 && <DataTable label="Issue lines" rows={lines.data?.lines ?? []} loading={lines.isPending} columns={columns} rowKey={(l) => l.issue_line_id} />}
      {issueId > 0 && <p className="text-xs text-muted-foreground">What was lost or damaged does not go back into stock: it raises a write-off request for the store to deal with.</p>}
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/outward/returns/${doc.id}` : '/store/hub/outward/returns')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!issueId || !picked.length || needsReason}>{doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
