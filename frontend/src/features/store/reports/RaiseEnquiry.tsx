import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShoppingCart } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { openRfq } from '@/api/rfq'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { num, type Row } from './api'

interface Line { key: string; item_code: string; item_name: string; uom: string; qty: string; stores: string[]; on: boolean }

/** The items the Reorder report shows, one line each (the same item low in two stores is one line, for both). */
function linesOf(rows: Row[]): Line[] {
  const out = new Map<string, Line>()
  for (const r of rows) {
    const code = String(r.item_code)
    const got = out.get(code)
    if (got) {
      got.qty = String(Number(got.qty) + Number(r.suggested_qty ?? 0))
      got.stores.push(String(r.store_code))
    } else out.set(code, { key: code, item_code: code, item_name: String(r.item_name), uom: String(r.base_uom ?? ''), qty: String(Number(r.suggested_qty ?? 0)), stores: [String(r.store_code)], on: true })
  }
  return [...out.values()]
}

/** From the Reorder report straight to a purchase enquiry for what is running low, at the suggested quantities. */
export function RaiseEnquiry({ rows }: { rows: Row[] }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)} disabled={!rows.length}><ShoppingCart /> Raise purchase enquiry</Button>
      <Modal open={open} onOpenChange={(o) => !o && setOpen(false)} size="lg" title="Raise a purchase enquiry"
        description="An enquiry for the items running low, at the quantity that brings each back up. Change what is needed, then ask suppliers for quotes from the enquiry.">
        {open && <Form rows={rows} onClose={() => setOpen(false)} />}
      </Modal>
    </>
  )
}

function Form({ rows, onClose }: { rows: Row[]; onClose: () => void }) {
  const nav = useNavigate()
  const projects = useProjects()
  const [lines, setLines] = useState(() => linesOf(rows))
  const stores = [...new Set(lines.flatMap((l) => l.stores))]
  const [f, setF] = useState({ title: `Reorder - ${stores.join(', ')}`.slice(0, 120), job_id: 0, needed_by: '' })
  const chosen = lines.filter((l) => l.on && Number(l.qty) > 0)
  const upd = (key: string, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const save = useAction(
    () => openRfq({ title: f.title.trim(), job_id: f.job_id || null, needed_by: f.needed_by, notes: `Raised from the Store Hub's Reorder report for ${stores.join(', ')}.`,
      lines: chosen.map((l) => ({ item_code: l.item_code, description: l.item_name, uom: l.uom, qty: Number(l.qty) })) }),
    { success: (d) => d.message, onSuccess: (d) => { onClose(); nav(`/store/enquiries/${d.rfq.id}`) } },
  )
  return (
    <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (chosen.length && f.title.trim()) save.mutate() }}>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Title" htmlFor="re-title" className="sm:col-span-3"><Input id="re-title" value={f.title} maxLength={120} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Project" htmlFor="re-proj" className="sm:col-span-2"><Select id="re-proj" value={f.job_id || ''} placeholder="Not for one project" onChange={(e) => setF({ ...f, job_id: Number(e.target.value) || 0 })} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Needed by" htmlFor="re-need"><Input id="re-need" type="date" min={today()} value={f.needed_by} onChange={(e) => setF({ ...f, needed_by: e.target.value })} /></Field>
      </div>
      <ul className="grid gap-2">
        {lines.map((l) => (
          <li key={l.key} className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2 text-sm">
            <input type="checkbox" aria-label={`Include ${l.item_name}`} checked={l.on} onChange={(e) => upd(l.key, { on: e.target.checked })} />
            <div className="min-w-0 flex-1"><div className="font-medium">{l.item_name}</div><div className="text-xs text-muted-foreground"><span className="font-mono">{l.item_code}</span> - low in {l.stores.join(', ')}</div></div>
            <label className="flex items-center gap-2">Qty <Input aria-label={`Quantity of ${l.item_name}`} inputMode="decimal" className="h-9 w-28 text-right" value={l.qty} disabled={!l.on} onChange={(e) => upd(l.key, { qty: e.target.value })} /> {l.uom}</label>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        <p className="mr-auto text-xs text-muted-foreground">{chosen.length} of {lines.length} items, {num(String(chosen.reduce((a, l) => a + Number(l.qty), 0)))} in all.</p>
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!chosen.length || !f.title.trim()}><ShoppingCart /> Raise the enquiry</Button>
      </div>
    </form>
  )
}
