import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui'
import { useUpdatePrompt } from '@/stores/updatePrompt'

/**
 * The box that offers a new version of the phone app, in the middle of the screen. It is only ever opened by the native
 * app (lib/mobile.ts), so in a browser it draws nothing. "Later" puts it away until the app is opened again.
 */
export function UpdatePrompt() {
  const { offer, close } = useUpdatePrompt()
  const [busy, setBusy] = useState(false)
  const take = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!offer) return
    setBusy(false)
    take.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [offer, close])

  if (!offer) return null
  const go = async () => {
    setBusy(true)
    try { await offer.onConfirm() } finally { close() }
  }
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-6 backdrop-blur-[3px]" onClick={close}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-title"
        className="w-full max-w-sm rounded-3xl border border-border bg-card p-6 text-center shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-primary/15 text-primary" aria-hidden="true">
          <svg viewBox="0 0 24 24" className="size-7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m0 0-4.5-4.5M12 15l4.5-4.5M5 21h14" /></svg>
        </div>
        <h2 id="update-title" className="text-lg font-bold">{offer.title}</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">{offer.message}</p>
        <div className="mt-6 grid gap-2">
          <Button ref={take} size="lg" loading={busy} onClick={go} className="w-full">{offer.confirmLabel}</Button>
          <Button variant="ghost" disabled={busy} onClick={close} className="w-full">Later</Button>
        </div>
      </div>
    </div>
  )
}
