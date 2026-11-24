import { useId } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Textarea } from '@/components/ui'
import type { Place } from '@/api/website'
import { ImageField } from './ImageField'

/** What one value in a section is, and how it is edited. The forms of the Website tab are drawn from these. */
export type Spec =
  | { kind: 'text'; label: string; hint?: string; long?: boolean; max?: number }
  | { kind: 'number'; label: string; hint?: string }
  | { kind: 'bool'; label: string }
  | { kind: 'image'; label: string; place: Place }
  | { kind: 'strings'; label: string; item: string; long?: boolean; hint?: string }
  | { kind: 'object'; fields: Record<string, Spec> }
  | { kind: 'list'; label: string; item: string; of: Record<string, Spec>; blank: (n: number) => Record<string, unknown>; title?: (v: Record<string, unknown>) => string }

type Obj = Record<string, unknown>

const move = <T,>(list: T[], i: number, by: number) => {
  const j = i + by
  if (j < 0 || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

function RowTools({ label, i, n, onMove, onRemove }: { label: string; i: number; n: number; onMove: (by: number) => void; onRemove: () => void }) {
  return (
    <div className="flex shrink-0 gap-1">
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Move ${label} up`} disabled={i === 0} onClick={() => onMove(-1)}><ArrowUp /></Button>
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Move ${label} down`} disabled={i === n - 1} onClick={() => onMove(1)}><ArrowDown /></Button>
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${label}`} onClick={onRemove}><Trash2 /></Button>
    </div>
  )
}

/** One value of a section, edited as its Spec says. */
export function Edit({ spec, value, onChange }: { spec: Spec; value: unknown; onChange: (v: unknown) => void }) {
  const id = useId()
  switch (spec.kind) {
    case 'text': {
      const v = typeof value === 'string' ? value : ''
      const max = spec.max ?? 3000
      return (
        <Field label={spec.label} hint={spec.hint} htmlFor={id}>
          {spec.long
            ? <Textarea id={id} rows={3} maxLength={max} value={v} onChange={(e) => onChange(e.target.value)} />
            : <Input id={id} maxLength={max} value={v} onChange={(e) => onChange(e.target.value)} />}
        </Field>
      )
    }
    case 'number':
      return (
        <Field label={spec.label} hint={spec.hint} htmlFor={id}>
          <Input id={id} inputMode="numeric" value={typeof value === 'number' ? String(value) : ''}
            onChange={(e) => { const t = e.target.value.replace(/[^\d]/g, ''); onChange(t ? Number(t) : null) }} />
        </Field>
      )
    case 'bool':
      return (
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="size-4 accent-primary" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {spec.label}
        </label>
      )
    case 'image':
      return <ImageField label={spec.label} place={spec.place} value={typeof value === 'string' ? value : ''} onChange={onChange} />
    case 'strings': {
      const list = Array.isArray(value) ? (value as string[]) : []
      return (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">{spec.label}</legend>
          {spec.hint && <p className="-mt-1 text-[13px] text-muted-foreground">{spec.hint}</p>}
          {list.map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              {spec.long
                ? <Textarea aria-label={`${spec.item} ${i + 1}`} rows={2} maxLength={3000} value={s} onChange={(e) => onChange(list.map((x, k) => (k === i ? e.target.value : x)))} />
                : <Input aria-label={`${spec.item} ${i + 1}`} maxLength={300} value={s} onChange={(e) => onChange(list.map((x, k) => (k === i ? e.target.value : x)))} />}
              <RowTools label={`${spec.item} ${i + 1}`} i={i} n={list.length} onMove={(by) => onChange(move(list, i, by))} onRemove={() => onChange(list.filter((_, k) => k !== i))} />
            </div>
          ))}
          <div><Button type="button" variant="outline" size="sm" onClick={() => onChange([...list, ''])}><Plus /> Add {spec.item.toLowerCase()}</Button></div>
        </fieldset>
      )
    }
    case 'object': {
      const obj = (value && typeof value === 'object' ? value : {}) as Obj
      return (
        <div className="grid gap-4">
          {Object.entries(spec.fields).map(([k, s]) => (
            <Edit key={k} spec={s} value={obj[k]} onChange={(v) => onChange({ ...obj, [k]: v })} />
          ))}
        </div>
      )
    }
    case 'list': {
      const list = Array.isArray(value) ? (value as Obj[]) : []
      return (
        <fieldset className="grid gap-3">
          <legend className="mb-1 text-sm font-medium">{spec.label}</legend>
          {list.length === 0 && <p className="text-[13px] text-muted-foreground">None yet. While there are none, this part of the page is left out.</p>}
          {list.map((item, i) => {
            const name = (spec.title?.(item) || `${spec.item} ${i + 1}`).trim()
            return (
              <details key={i} className="rounded-lg border border-border bg-card" open={list.length <= 2}>
                <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-2.5 text-sm font-medium">
                  <span className="min-w-0 truncate">{name}</span>
                  <span onClick={(e) => e.preventDefault()}>
                    <RowTools label={name} i={i} n={list.length} onMove={(by) => onChange(move(list, i, by))} onRemove={() => onChange(list.filter((_, k) => k !== i))} />
                  </span>
                </summary>
                <div className="border-t border-border p-4">
                  <Edit spec={{ kind: 'object', fields: spec.of }} value={item} onChange={(v) => onChange(list.map((x, k) => (k === i ? (v as Obj) : x)))} />
                </div>
              </details>
            )
          })}
          <div><Button type="button" variant="outline" size="sm" onClick={() => onChange([...list, spec.blank(list.length)])}><Plus /> Add {spec.item.toLowerCase()}</Button></div>
        </fieldset>
      )
    }
  }
}
