import { useEffect, useState } from 'react'
import { Button } from '@/components/ui'
import { saveHeld, shareHeld } from '@/lib/download'
import { useFileSheet } from '@/stores/fileSheet'

/**
 * What to do with a PDF or Excel file the phone app has just fetched: keep a copy on the phone, or share it. Only the native
 * app ever fills the store (lib/download.ts), so in a browser this draws nothing.
 */
export function FileSheet() {
  const { file, close } = useFileSheet()
  const [busy, setBusy] = useState<'save' | 'share' | null>(null)

  useEffect(() => {
    if (!file) return
    setBusy(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [file, close])

  if (!file) return null
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/60 p-4 sm:items-center" onClick={close}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="file-sheet-title"
        className="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-md"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="file-sheet-title" className="text-lg font-bold">File ready</h2>
        <p className="mt-1 break-all text-sm text-muted-foreground">{file.name}</p>
        <div className="mt-5 grid gap-2">
          <Button
            size="lg"
            loading={busy === 'save'}
            disabled={busy !== null}
            onClick={async () => { setBusy('save'); if (await saveHeld(file)) close(); else setBusy(null) }}
            className="w-full"
          >
            Save to phone
          </Button>
          <Button
            size="lg"
            variant="outline"
            loading={busy === 'share'}
            disabled={busy !== null}
            onClick={async () => { setBusy('share'); await shareHeld(file); close() }}
            className="w-full"
          >
            Share
          </Button>
          <Button variant="ghost" disabled={busy !== null} onClick={close} className="w-full">Close</Button>
        </div>
      </div>
    </div>
  )
}
