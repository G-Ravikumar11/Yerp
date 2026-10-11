import { useEffect, useState } from 'react'
import { Button, Field, Input, Skeleton } from '@/components/ui'
import { PictureField } from '@/components/data/PictureField'
import { useAction } from '@/lib/mutate'
import { saveSignatories, settingsKeys, useSignatories, type Signatory } from '@/api/settings'
import { Section } from './Section'

const ORDER = ['prepared', 'proposed', 'recommended', 'authorised']

/** Who signs the company's documents, and the seal stamped beside them. */
export function Signatories() {
  const q = useSignatories()
  const [sig, setSig] = useState<Record<string, Signatory>>({})
  const [seal, setSeal] = useState('')
  useEffect(() => {
    if (!q.data) return
    setSig(q.data.signatories)
    setSeal(q.data.seal)
  }, [q.data])
  const save = useAction(
    () => saveSignatories({ ...Object.fromEntries(Object.entries(sig).map(([k, s]) => [k, { name: s.name, title: s.title, image: s.image }])), seal }),
    { invalidate: [settingsKeys.all] },
  )
  const edit = (k: string, patch: Partial<Signatory>) => setSig((s) => ({ ...s, [k]: { ...s[k], ...patch } }))
  if (q.isPending) return <Skeleton className="h-64 w-full" />
  const keys = ORDER.filter((k) => sig[k])
  return (
    <Section title="Signatures and seal" description="Every work order, bill and statement signs with these.">
      <div className="grid gap-5 md:grid-cols-2">
        {keys.map((k) => (
          <div key={k} className="rounded-lg border border-border p-4">
            <p className="mb-3 text-sm font-semibold">{sig[k].role}</p>
            <div className="grid gap-3">
              <Field label="Name" htmlFor={`sig-${k}-name`}><Input id={`sig-${k}-name`} value={sig[k].name} onChange={(e) => edit(k, { name: e.target.value })} /></Field>
              <Field label="Designation" htmlFor={`sig-${k}-title`}><Input id={`sig-${k}-title`} value={sig[k].title} onChange={(e) => edit(k, { title: e.target.value })} /></Field>
              <PictureField label={`${sig[k].role} signature`} value={sig[k].image} onChange={(v) => edit(k, { image: v })} maxW={400} maxH={140} clearWhite />
            </div>
          </div>
        ))}
        <div className="rounded-lg border border-border p-4">
          <p className="mb-3 text-sm font-semibold">Company seal</p>
          <PictureField label="Seal" value={seal} onChange={setSeal} maxW={300} maxH={300} clearWhite />
        </div>
      </div>
      <Button className="mt-4" loading={save.isPending} onClick={() => save.mutate()}>Save signatures</Button>
    </Section>
  )
}
