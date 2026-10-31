import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Input, Select } from '@/components/ui'
import { get, put } from '@/lib/api'
import { schKeys, type Activity } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

const useReasons = () => useQuery({ queryKey: ['schedule', 'delay-reasons'], staleTime: Infinity, queryFn: async () => (await get<{ reasons: string[] }>('/api/delay-reasons')).reasons })

/** How late an activity is against its baseline, and why: a hindrance against it on the register, or a reason given here.
 * A late activity with neither is flagged until one is given. */
export function DelayReason({ a, can, onHindrance }: { a: Activity; can: boolean; onHindrance: () => void }) {
  const reasons = useReasons()
  const [reason, setReason] = useState(a.delay_reason ?? '')
  const [note, setNote] = useState(a.delay_note ?? '')
  const save = useAction((clear: boolean) => put<{ message?: string }>(`/api/schedule/activities/${a.id}/delay-reason`, clear ? { reason: '' } : { reason, note }), { invalidate: [schKeys.all] })
  if (!a.delay_days && !a.delay_reason) return null
  const against = a.measured_against === 'baseline' ? 'the baseline' : 'the plan (no baseline saved yet)'
  return (
    <section aria-label="Delay" className={`mb-5 rounded-xl border p-4 text-sm ${a.needs_reason ? 'border-danger/40 bg-danger-soft' : 'border-border bg-card'}`}>
      <p className="mb-2">
        {a.delay_days ? <><strong>{a.delay_days} days late</strong> against {against}: promised by <strong>{formatDate(a.baseline_finish)}</strong>{a.actual_percent >= 100 ? '' : `, forecast ${formatDate(a.forecast_finish)}`}.</> : 'Not late now.'}
        {a.hindrances?.length ? <> Explained by {a.hindrances.join(', ')} on the hindrance register.</> : null}
        {a.needs_reason && <> <strong>Nothing says why.</strong> Record a hindrance, or give a reason.</>}
      </p>
      {can && (
        <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Reason for the delay" className="w-60" value={reason} onChange={(e) => setReason(e.target.value)} options={[{ value: '', label: 'Choose a reason' }, ...(reasons.data ?? []).map((r) => ({ value: r, label: r }))]} />
          <Input aria-label="More about the reason" className="min-w-48 flex-1" value={note} placeholder={reason === 'Other' ? 'Say what it was' : 'A word more (optional)'} onChange={(e) => setNote(e.target.value)} />
          <Button size="sm" disabled={!reason} loading={save.isPending} onClick={() => save.mutate(false)}>Keep the reason</Button>
          {a.delay_reason && <Button size="sm" variant="ghost" onClick={() => { setReason(''); setNote(''); save.mutate(true) }}>Take it away</Button>}
          <Button size="sm" variant="outline" onClick={onHindrance}>Record a hindrance</Button>
        </div>
      )}
      {save.error && <p role="alert" className="mt-2 text-[13px] text-danger">{save.error.message}</p>}
    </section>
  )
}
