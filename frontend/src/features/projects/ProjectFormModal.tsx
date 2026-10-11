import { useState } from 'react'
import { LocateFixed } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { JOB_STATUS, clearSiteLocation, projectKeys, saveProject, setSiteLocation, useGstStates, useSiteLocation, type BoardProject } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { toast } from '@/stores/toast'

export function ProjectFormModal({ project, open, onClose }: { project: BoardProject | null; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={project ? `Edit ${project.number}` : 'New project'} description="Every quote, bill and order can be filed against a project." size="lg">
      {open && <Form key={project?.id ?? 'new'} project={project} onClose={onClose} />}
    </Modal>
  )
}

function Form({ project: p, onClose }: { project: BoardProject | null; onClose: () => void }) {
  const states = useGstStates()
  const loc = useSiteLocation(p?.id ?? null)
  const [f, setF] = useState({ name: p?.name ?? '', customer_name: p?.customer_name ?? '', status: p?.status ?? 'quoting', site_address: p?.site_address ?? '', state_code: p?.state_code ?? '', start_date: p?.start_date ?? today(), target_end_date: p?.target_end_date ?? '', description: p?.description ?? '' })
  const [n, setN] = useState({ quoted_value: p?.quoted_value ?? 0, budget: p?.budget ?? 0, retention_percent: p?.retention_percent ?? 0 })
  const [geo, setGeo] = useState<string | null>(null)
  const [radius, setRadius] = useState<number | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  // Standing on the site: where the phone or laptop is.
  const here = () => {
    if (!navigator.geolocation) return toast.error('This browser cannot tell where it is')
    navigator.geolocation.getCurrentPosition((pos) => { setGeo(`${pos.coords.latitude.toFixed(6)}, ${pos.coords.longitude.toFixed(6)}`); toast.success(`Position taken - accurate to about ${Math.round(pos.coords.accuracy)} m`) }, () => toast.error('Location was not allowed'), { enableHighAccuracy: true, timeout: 15000 })
  }
  const shownGeo = geo ?? (loc.data?.set ? `${loc.data.lat}, ${loc.data.lng}` : '')
  const shownRadius = radius ?? (loc.data?.set ? loc.data.radius_m ?? 300 : 0)
  const save = useAction(async () => {
    const r = await saveProject(p?.id ?? null, { ...f, ...n })
    const id = p?.id ?? (r as { id: number }).id
    if (geo !== null || radius !== null) {
      if (!shownGeo.trim()) { if (loc.data?.set) await clearSiteLocation(id) } else await setSiteLocation(id, shownGeo.trim(), shownRadius || 300)
    }
    return { message: p ? 'Project updated' : 'Project created' }
  }, { invalidate: [projectKeys.all], onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Project name" htmlFor="pj-name" className="sm:col-span-2"><Input id="pj-name" value={f.name} onChange={set('name')} placeholder="Fairview, plot 3" autoFocus /></Field>
        <Field label="Customer" htmlFor="pj-cust"><Input id="pj-cust" value={f.customer_name} onChange={set('customer_name')} /></Field>
        <Field label="Status" htmlFor="pj-status"><Select id="pj-status" value={f.status} onChange={set('status')} options={Object.entries(JOB_STATUS).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Site address" htmlFor="pj-site" className="sm:col-span-2"><Input id="pj-site" value={f.site_address} onChange={set('site_address')} /></Field>
        <Field label="State the site is in" htmlFor="pj-state" hint="Decides the GST place of supply" className="sm:col-span-2"><Select id="pj-state" value={f.state_code} placeholder="Not set" onChange={set('state_code')} options={Object.entries(states.data ?? {}).sort((a, b) => a[0].localeCompare(b[0])).map(([k, v]) => ({ value: k, label: `${k} - ${v}` }))} /></Field>
        <div className="sm:col-span-2">
          <p className="mb-1.5 text-sm font-medium">Site location, for attendance</p>
          <div className="flex gap-2">
            <Input aria-label="Site location" value={shownGeo} onChange={(e) => setGeo(e.target.value)} placeholder="17.4239, 78.3413 - or paste a Google Maps link" />
            <div className="w-28"><NumField aria-label="Radius in metres" placeholder="300 m" value={shownRadius} onValue={setRadius} /></div>
            <Button type="button" variant="outline" onClick={here} title="Standing on site? Use where you are"><LocateFixed /> Here</Button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Staff who clock in inside it are counted on this project.</p>
        </div>
        <Field label="Quoted value" htmlFor="pj-quoted"><NumField id="pj-quoted" value={n.quoted_value} onValue={num('quoted_value')} /></Field>
        <Field label="Cost budget" htmlFor="pj-budget"><NumField id="pj-budget" value={n.budget} onValue={num('budget')} /></Field>
        <Field label="Retention %" htmlFor="pj-ret"><NumField id="pj-ret" value={n.retention_percent} onValue={num('retention_percent')} /></Field>
        <span />
        <Field label="Start" htmlFor="pj-start"><Input id="pj-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Target finish" htmlFor="pj-end"><Input id="pj-end" type="date" value={f.target_end_date} onChange={set('target_end_date')} /></Field>
        <Field label="Notes" htmlFor="pj-notes" className="sm:col-span-2"><Textarea id="pj-notes" rows={2} value={f.description} onChange={set('description')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Save project</Button>
      </div>
    </div>
  )
}
