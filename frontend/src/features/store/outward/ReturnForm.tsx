import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, Input } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storeGet, storePost } from '@/api/store'
import { errText, num, type Issue, type IssueReturn } from './types'

interface Returnable { issue: { id: number; number: string; holder_name: string }; lines: { issue_line_id: number; item_name: string; item_code: string; base_uom: string; issued_qty: string; still_out_qty: string }[] }

/** Material coming back from an issue (/returns/new?issue=ID): the quantity returned and any declared lost. */
export function ReturnForm() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const issueId = params.get('issue') ?? ''
  const [vals, setVals] = useState<Record<number, { qty: string; lost: string; why: string }>>({})
  const [remarks, setRemarks] = useState('')
  const issue = useQuery({ queryKey: ['store', 'outward', 'issues', issueId], enabled: !!issueId, queryFn: () => storeGet<Issue>('outward', `/issues/${issueId}`) })
  const lines = useQuery({ queryKey: ['store', 'outward', 'returnable', issueId], enabled: !!issueId, queryFn: () => storeGet<Returnable>('outward', `/issues/${issueId}/returnable`) })
  const v = (id: number) => vals[id] ?? { qty: '', lost: '', why: '' }
  const put = (id: number, patch: Partial<{ qty: string; lost: string; why: string }>) => setVals({ ...vals, [id]: { ...v(id), ...patch } })
  const save = useMutation({
    mutationFn: () => storePost<IssueReturn>('outward', '/returns', {
      store_id: issue.data?.store_id, issue_id: Number(issueId), remarks,
      lines: Object.entries(vals).filter(([, x]) => Number(x.qty) > 0 || Number(x.lost) > 0).map(([id, x]) => ({ issue_line_id: Number(id), qty: x.qty || '0', lost_qty: x.lost || '0', remarks: x.why })),
    }),
    onSuccess: (r) => { toast.success(`${r.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'outward'] }); nav(`/store/hub/outward/returns/${r.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
  if (!issueId) return <p className="text-sm text-muted-foreground">Open a posted issue and choose Record a return.</p>
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">Return against {lines.data?.issue.number} · held by {lines.data?.issue.holder_name || 'nobody named'}</p>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3 text-right">Still out</th><th className="p-3 text-right">Returned</th><th className="p-3 text-right">Lost</th><th className="p-3">Why lost</th></tr></thead>
          <tbody>
            {(lines.data?.lines ?? []).map((l) => {
              const none = Number(l.still_out_qty) <= 0
              return (
                <tr key={l.issue_line_id} className="border-b border-border last:border-0">
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td>
                  <td className="p-3 text-right">{num(l.still_out_qty)} {l.base_uom}</td>
                  <td className="p-3 text-right"><Input className="ml-auto w-24 text-right" inputMode="decimal" disabled={none} value={v(l.issue_line_id).qty} onChange={(e) => put(l.issue_line_id, { qty: e.target.value })} /></td>
                  <td className="p-3 text-right"><Input className="ml-auto w-24 text-right" inputMode="decimal" disabled={none} value={v(l.issue_line_id).lost} onChange={(e) => put(l.issue_line_id, { lost: e.target.value })} /></td>
                  <td className="p-3"><Input value={v(l.issue_line_id).why} disabled={!Number(v(l.issue_line_id).lost)} onChange={(e) => put(l.issue_line_id, { why: e.target.value })} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
      <label className="block text-sm">Remarks<Input value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
      <div className="flex gap-2"><Button loading={save.isPending} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={() => nav('/store/hub/outward')}>Back</Button></div>
    </div>
  )
}
