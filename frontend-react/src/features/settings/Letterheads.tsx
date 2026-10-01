import { useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { Button, Field, Input, Modal, Skeleton, Textarea } from '@/components/ui'
import { PictureField } from '@/components/data/PictureField'
import { useAction } from '@/lib/mutate'
import { addBusinessUnit, saveBusinessUnit, settingsKeys, useBusinessUnits, type BusinessUnit, type UnitBody } from '@/api/settings'
import { Section } from './Section'

const blank: UnitBody = { name: '', code: '', gstin: '', pan: '', address: '', logo_url: '' }

function UnitModal({ unit, onClose }: { unit: BusinessUnit | 'new'; onClose: () => void }) {
  const [f, setF] = useState<UnitBody>(blank)
  useEffect(() => setF(unit === 'new' ? blank : { name: unit.name, code: unit.code, gstin: unit.gstin, pan: unit.pan, address: unit.address, logo_url: unit.logo_url }), [unit])
  const set = (k: keyof UnitBody) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))
  const save = useAction(() => (unit === 'new' ? addBusinessUnit(f) : saveBusinessUnit(unit.id, f)), { invalidate: [settingsKeys.all], onSuccess: onClose })
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={unit === 'new' ? 'New letterhead' : `Letterhead - ${unit.name}`}
      description="How the name, address and tax numbers print at the top of the documents this unit issues."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Save letterhead</Button></>}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="lh-name"><Input id="lh-name" value={f.name} onChange={set('name')} /></Field>
        <Field label="Short code" htmlFor="lh-code"><Input id="lh-code" value={f.code} onChange={set('code')} /></Field>
        <Field label="GSTIN" htmlFor="lh-gstin"><Input id="lh-gstin" value={f.gstin} onChange={set('gstin')} /></Field>
        <Field label="PAN" htmlFor="lh-pan"><Input id="lh-pan" value={f.pan} onChange={set('pan')} /></Field>
        <Field label="Address" htmlFor="lh-addr" className="sm:col-span-2"><Textarea id="lh-addr" rows={3} value={f.address} onChange={set('address')} /></Field>
        <div className="sm:col-span-2"><PictureField label="Logo" value={f.logo_url} onChange={(v) => setF((s) => ({ ...s, logo_url: v }))} /></div>
      </div>
    </Modal>
  )
}

/** The company and its other units, each with its own name, tax numbers and logo on paper. */
export function Letterheads() {
  const q = useBusinessUnits()
  const [editing, setEditing] = useState<BusinessUnit | 'new' | null>(null)
  const units = q.data?.business_units ?? []
  return (
    <Section
      title="Letterheads"
      description="One for each company or division that issues documents. Work orders pick the one they are issued from."
      actions={<Button size="sm" variant="outline" onClick={() => setEditing('new')}><Plus /> Add a letterhead</Button>}
    >
      {q.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <ul className="divide-y divide-border">
          {units.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-md border border-border bg-white">
                {u.logo_url ? <img src={u.logo_url} alt="" className="max-h-full max-w-full" /> : <span className="text-[10px] text-neutral-500">No logo</span>}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{u.name}{u.code && <span className="ml-2 text-xs text-muted-foreground">{u.code}</span>}</p>
                <p className="truncate text-xs text-muted-foreground">{[u.gstin && `GSTIN ${u.gstin}`, u.pan && `PAN ${u.pan}`, u.address].filter(Boolean).join(' · ') || 'No details yet'}</p>
              </div>
              <Button size="sm" variant="outline" aria-label={`Edit letterhead ${u.name}`} onClick={() => setEditing(u)}>Edit</Button>
            </li>
          ))}
          {!units.length && <li className="py-4 text-sm text-muted-foreground">No letterheads yet.</li>}
        </ul>
      )}
      {editing && <UnitModal unit={editing} onClose={() => setEditing(null)} />}
    </Section>
  )
}
