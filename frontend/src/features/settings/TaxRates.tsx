import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input, NumField, Skeleton } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { saveTaxRates, settingsKeys, useTaxRates, type TaxRate } from '@/api/settings'
import { Section } from './Section'

/** The tax rates the line editors offer; exactly one is the default. */
export function TaxRates() {
  const q = useTaxRates()
  const [rows, setRows] = useState<TaxRate[]>([])
  useEffect(() => { if (q.data) setRows(q.data.map((r) => ({ name: r.name, percent: r.percent, is_default: r.is_default }))) }, [q.data])
  const save = useAction(() => saveTaxRates(rows), { invalidate: [settingsKeys.all], success: 'Tax rates saved.' })
  const edit = (i: number, patch: Partial<TaxRate>) => setRows((l) => l.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const makeDefault = (i: number) => setRows((l) => l.map((r, j) => ({ ...r, is_default: j === i })))
  return (
    <Section title="Tax rates" description="Offered on every line of an order, bill or estimate. One of them is the default.">
      {q.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_6rem_auto_auto] items-center gap-2">
                <Input aria-label={`Tax rate ${i + 1} name`} placeholder="Name, e.g. GST" value={r.name} onChange={(e) => edit(i, { name: e.target.value })} />
                <NumField aria-label={`Tax rate ${i + 1} percent`} value={r.percent} onValue={(n) => edit(i, { percent: n })} />
                <label className="flex items-center gap-1.5 text-[13px]"><input type="radio" name="default-tax" checked={r.is_default} onChange={() => makeDefault(i)} /> Default</label>
                <Button type="button" variant="ghost" size="icon" aria-label={`Remove tax rate ${i + 1}`} onClick={() => setRows((l) => l.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setRows((l) => [...l, { name: '', percent: 0, is_default: false }])}><Plus /> Add a rate</Button>
            <Button type="button" loading={save.isPending} onClick={() => save.mutate()}>Save tax rates</Button>
          </div>
        </>
      )}
    </Section>
  )
}
