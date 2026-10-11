import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { assetKeys, saveBook, type BookInput } from '@/api/assets'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

export interface BookTarget {
  id: number
  title: string
  setUp: boolean
  book: Partial<BookInput>
}

/** How an owned asset is written down: the method, its life, what it cost and when it went into use. */
export function BookModal({ target, blocks, methods, onClose }: { target: BookTarget | null; blocks: string[]; methods: string[]; onClose: () => void }) {
  return (
    <Modal open={!!target} onOpenChange={(o) => !o && onClose()} size="lg" title={target ? `${target.setUp ? 'Book for' : 'Set up the book for'} ${target.title}` : 'Book'}>
      {target && <Form key={target.id} target={target} blocks={blocks} methods={methods} onClose={onClose} />}
    </Modal>
  )
}

function Form({ target, blocks, methods, onClose }: { target: BookTarget; blocks: string[]; methods: string[]; onClose: () => void }) {
  const b = target.book
  const [f, setF] = useState<BookInput>({ method: b.method ?? 'WDV', life_years: b.life_years ?? 0, residual_percent: b.residual_percent ?? 5, put_to_use_on: b.put_to_use_on ?? '', cost: b.cost ?? 0, tax_block: b.tax_block ?? blocks[0] ?? '', opening_fy: b.opening_fy ?? '', opening_book_value: b.opening_book_value ?? 0 })
  const set = (k: keyof BookInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const num = (k: keyof BookInput) => (n: number) => setF((s) => ({ ...s, [k]: n }))
  const save = useAction(() => saveBook(target.id, f), { invalidate: [assetKeys.all], onSuccess: onClose })

  let rate: React.ReactNode = null
  if (f.life_years > 0 && f.cost > 0) {
    const floor = (f.cost * f.residual_percent) / 100
    if (f.method === 'SLM') rate = `${formatINR((f.cost - floor) / f.life_years)} a year, down to ${formatINR(floor)}`
    else if (f.residual_percent > 0) rate = `${Math.round((1 - Math.pow(f.residual_percent / 100, 1 / f.life_years)) * 10000) / 100}% a year on what is left, down to ${formatINR(floor)}`
    else rate = <span className="text-danger">Written-down value needs a residual above nought.</span>
  }

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Method" htmlFor="ab-method"><Select id="ab-method" value={f.method} onChange={set('method')} options={methods.map((m) => ({ value: m, label: m === 'SLM' ? 'SLM (straight line)' : 'WDV (written-down value)' }))} /></Field>
        <Field label="Life (years)" htmlFor="ab-life"><NumField id="ab-life" value={f.life_years} onValue={num('life_years')} /></Field>
        <Field label="Residual %" htmlFor="ab-res"><NumField id="ab-res" value={f.residual_percent} onValue={num('residual_percent')} /></Field>
        <Field label="Cost" htmlFor="ab-cost"><NumField id="ab-cost" value={f.cost} onValue={num('cost')} /></Field>
        <Field label="Put to use on" htmlFor="ab-put"><Input id="ab-put" type="date" value={f.put_to_use_on} onChange={set('put_to_use_on')} /></Field>
        <Field label="Income-tax block" htmlFor="ab-block"><Select id="ab-block" value={f.tax_block} onChange={set('tax_block')} options={blocks.map((x) => ({ value: x, label: x }))} /></Field>
      </div>
      {rate && <p className="mt-3 text-sm text-muted-foreground" role="status">{rate}</p>}
      <details className="mt-4 text-sm" open={!!f.opening_fy}>
        <summary className="cursor-pointer">An old asset, opened part-way through its life</summary>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="Opening year" htmlFor="ab-ofy" hint="e.g. 2024-25"><Input id="ab-ofy" value={f.opening_fy} onChange={set('opening_fy')} /></Field>
          <Field label="Book value at the start of it" htmlFor="ab-oval"><NumField id="ab-oval" value={f.opening_book_value} onValue={num('opening_book_value')} /></Field>
        </div>
      </details>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={f.life_years <= 0 || f.cost <= 0} onClick={() => save.mutate()}>Save the book</Button>
      </div>
    </div>
  )
}
