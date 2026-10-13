import { useEffect, useState } from 'react'
import { Browser } from '@capacitor/browser'
import { Capacitor } from '@capacitor/core'
import { Button, Modal, Skeleton } from '@/components/ui'
import { apiUrl, post } from '@/lib/api'
import { toast } from '@/stores/toast'

const native = Capacitor.isNativePlatform()

/**
 * A stored file fetched with the session cookie and held as a blob URL, so it shows in the phone app too, where a bare
 * relative path points at the app itself rather than the server. With `imagesOnly`, anything that is not a picture is
 * not downloaded at all (`other` says so): a PDF or a drawing is opened another way, and could be 15 MB.
 */
export function useFileBlob(path: string, enabled = true, imagesOnly = false) {
  const [src, setSrc] = useState('')
  const [type, setType] = useState('')
  const [failed, setFailed] = useState(false)
  const [other, setOther] = useState(false)
  useEffect(() => {
    if (!enabled || !path) return
    let url = ''
    let live = true
    setFailed(false)
    setOther(false)
    fetch(apiUrl(path), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status))
        const kind = (r.headers.get('content-type') || '').split(';')[0].trim()
        if (imagesOnly && !kind.startsWith('image/')) {
          void r.body?.cancel()
          if (live) { setType(kind); setOther(true) }
          return
        }
        const b = await r.blob()
        if (live) { url = URL.createObjectURL(b); setType(b.type); setSrc(url) }
      })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false; if (url) URL.revokeObjectURL(url) }
  }, [path, enabled, imagesOnly])
  return { src, type, failed, other }
}

/**
 * A PDF or a drawing in the phone app, which cannot show one itself: it is opened in the phone's own browser, which
 * downloads it and offers whatever app can read it. That browser has none of the app's sign-in, so the server is asked
 * for a link that works on its own for this file for a few minutes.
 */
export async function openOutside(id: number) {
  try {
    const { url } = await post<{ url: string }>(`/api/files/${id}/link`)
    await Browser.open({ url: apiUrl(url) })
  } catch {
    toast.error('That file could not be opened. Check the connection and try again.')
  }
}

/** A picture opened full size inside the app; any other file is handed to the phone's own browser. */
export function FileViewer({ name, id, onClose }: { name: string; id: number; onClose: () => void }) {
  const { src, failed, other } = useFileBlob(`/api/files/${id}`, true, true)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={name} size="xl">
      {failed ? <p className="text-sm text-danger">This could not be opened. Check the connection and try again.</p>
        : other ? <Button onClick={() => void openOutside(id)}>Open or save {name}</Button>
        : !src ? <Skeleton className="h-64 w-full" />
        : <img src={src} alt={name} className="mx-auto max-h-[75vh] max-w-full rounded-md object-contain" />}
    </Modal>
  )
}

/**
 * "Open" for a stored file. In a browser it opens in its own tab, as it always did. In the phone app a picture opens
 * full size inside it, and a PDF or a drawing goes to the phone's own browser.
 */
export function OpenFile({ id, name, className, children }: { id: number; name: string; className?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  if (!native) return <a className={className} href={apiUrl(`/api/files/${id}`)} target="_blank" rel="noopener">{children}</a>
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>{children}</button>
      {open && <FileViewer name={name} id={id} onClose={() => setOpen(false)} />}
    </>
  )
}
