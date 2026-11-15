import { useState } from 'react'
import { Globe, ImagePlus } from 'lucide-react'
import { Button, Field, Input, Modal, Textarea } from '@/components/ui'
import { FilesModal } from '@/components/data/FilesModal'
import { saveProjectWebsite, type ProjectWebsite } from '@/api/projects'
import { useAction } from '@/lib/mutate'

/** Show a project on the company website, or take it off, with what its public card says. Its value and costs never go. */
export function ProjectWebsiteButton({ id, name, website }: { id: number; name: string; website?: ProjectWebsite }) {
  const [open, setOpen] = useState(false)
  const start = website ?? { show: false, sector: '', location: '', scope: '' }
  const [form, setForm] = useState(start)
  const [photos, setPhotos] = useState(false)
  const save = useAction(() => saveProjectWebsite(id, form), { invalidate: [['projects']], onSuccess: () => setOpen(false) })
  const set = (k: keyof ProjectWebsite) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm((f) => ({ ...f, [k]: e.target.value }))
  return (
    <>
      <Button variant="outline" onClick={() => { setForm(start); setOpen(true) }}><Globe /> {start.show ? 'On website' : 'Website'}</Button>
      <Modal open={open} onOpenChange={setOpen} title={`${name} on the company website`}
        description="Shown on the website with the photos kept against the project (not its diary photos). Only what is below and the client's name are shown - never its value or costs.">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" className="size-4" checked={form.show} onChange={(e) => setForm((f) => ({ ...f, show: e.target.checked }))} /> Show on website
          </label>
          <Field label="Sector" htmlFor="web-sector" hint="e.g. Residential, Hospital, Metro rail, Water"><Input id="web-sector" value={form.sector} maxLength={60} onChange={set('sector')} /></Field>
          <Field label="Place" htmlFor="web-place" hint="City, as the public should see it"><Input id="web-place" value={form.location} maxLength={80} onChange={set('location')} /></Field>
          <Field label="Scope" htmlFor="web-scope" hint="One or two lines on what we did there"><Textarea id="web-scope" value={form.scope} maxLength={600} rows={3} onChange={set('scope')} /></Field>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <Button type="button" variant="outline" className="mr-auto" onClick={() => { setOpen(false); setPhotos(true) }}><ImagePlus /> Project photos</Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={save.isPending}>Save</Button>
          </div>
        </form>
      </Modal>
      {photos && <FilesModal type="job" id={id} title={`${name} - photos`} onClose={() => setPhotos(false)} />}
    </>
  )
}
