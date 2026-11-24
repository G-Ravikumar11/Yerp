import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ImageIcon, Upload } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { pictureUrl, uploadImage, useWebsiteImages, websiteKeys, type Place } from '@/api/website'
import { ApiError } from '@/lib/api'
import { toast } from '@/stores/toast'
import { BUILT_IN } from '@/features/site/siteContent'
import { Cropper, SHAPES } from './Cropper'

/** The photographs the site was built with, so one taken out can be put back. */
const builtIn = () => {
  const s = BUILT_IN.SITE
  return [...new Set([...s.slides, ...s.capabilities, ...s.sitePhotos].map((x) => x.img).filter(Boolean))]
}

/** Choose a photo for the website and crop it to the place's shape, then upload it. Resolves to its path, or null. */
export function useUpload(place: Place, jobId = 0) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const done = useRef<(path: string, id: number) => void>(() => undefined)
  const pick = (then: (path: string, id: number) => void) => { done.current = then; input.current?.click() }
  const ui = (
    <>
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" aria-hidden tabIndex={-1}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) setFile(f) }} />
      {file && <Cropper file={file} place={place} busy={busy} onCancel={() => setFile(null)} onDone={async (blob) => {
        setBusy(true)
        try {
          const res = await uploadImage(blob, file.name.replace(/\.[^.]+$/, '') + '.jpg', place, jobId)
          await qc.invalidateQueries({ queryKey: websiteKeys.all })
          toast.success(`Picture uploaded (${Math.round(blob.size / 1024)} KB).`)
          setFile(null)
          done.current(res.path, res.id)
        } catch (e) {
          toast.error(e instanceof ApiError ? e.message : 'The picture could not be uploaded. Try again.')
        } finally {
          setBusy(false)
        }
      }} />}
    </>
  )
  return { pick, ui }
}

/** A picture in a section: what is there now, a new one uploaded and cropped to the place's shape, or one already up. */
export function ImageField({ label, place, value, onChange }: { label: string; place: Place; value: string; onChange: (v: string) => void }) {
  const upload = useUpload(place)
  const [choosing, setChoosing] = useState(false)
  const { w, h } = SHAPES[place]
  return (
    <div className="grid gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid w-32 shrink-0 place-items-center overflow-hidden rounded-md bg-muted ring-1 ring-border" style={{ aspectRatio: `${w} / ${h}` }}>
          {value ? <img src={pictureUrl(value, true)} alt="" className="size-full object-cover" /> : <ImageIcon className="size-5 text-muted-foreground" aria-hidden />}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => upload.pick((path) => onChange(path))}><Upload /> Upload new</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setChoosing(true)}><ImageIcon /> Choose one</Button>
        </div>
      </div>
      {upload.ui}
      {choosing && <Library place={place} onClose={() => setChoosing(false)} onPick={(p) => { onChange(p); setChoosing(false) }} />}
    </div>
  )
}

function Library({ place, onPick, onClose }: { place: Place; onPick: (path: string) => void; onClose: () => void }) {
  const q = useWebsiteImages()
  const mine = (q.data?.images ?? []).filter((i) => i.place === place || place === 'section')
  const tile = (path: string, name: string) => (
    <li key={path}>
      <button type="button" onClick={() => onPick(path)} className="block w-full overflow-hidden rounded-md ring-1 ring-border hover:ring-2 hover:ring-primary focus-visible:ring-2 focus-visible:ring-primary">
        <img src={pictureUrl(path, true)} alt={name} className="aspect-[4/3] w-full object-cover" loading="lazy" />
      </button>
    </li>
  )
  return (
    <Modal open onOpenChange={(o) => { if (!o) onClose() }} title="Choose a picture" size="lg">
      <div className="grid gap-4">
        {mine.length > 0 && <section><h3 className="mb-2 text-sm font-semibold">Uploaded</h3><ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">{mine.map((i) => tile(i.path, i.name))}</ul></section>}
        <section><h3 className="mb-2 text-sm font-semibold">The site&apos;s own photos</h3><ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">{builtIn().map((p) => tile(p, p.split('/').pop() ?? p))}</ul></section>
      </div>
    </Modal>
  )
}
