import { useEffect, useRef, useState } from 'react'
import { ScanLine } from 'lucide-react'
import { Button, Input, Modal } from '@/components/ui'
import { cn } from '@/lib/utils'

/**
 * Scanning a code with the phone's camera: a QR on a rack or yard-bay tag, an item's rack label, the maker's barcode on a
 * bag or a can, the QR on a gate pass. The code can also be typed, or read by a handheld scanner, which types it.
 * The camera library is loaded only when a scan is started.
 */
export function ScanDialog({ open, onClose, onCode, title = 'Scan a code', hint }: { open: boolean; onClose: () => void; onCode: (code: string) => void; title?: string; hint?: string }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={title} description={hint ?? 'Point the camera at the QR code or barcode. It is read as soon as it is in view.'}>
      {open && <Camera onCode={(c) => { onClose(); onCode(c) }} />}
    </Modal>
  )
}

function Camera({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [state, setState] = useState<'starting' | 'live' | 'blocked' | 'none'>('starting')
  const [typed, setTyped] = useState('')
  const done = useRef(false)
  useEffect(() => {
    let stop: (() => void) | null = null
    let gone = false
    void (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setState('none')
        return
      }
      try {
        const { BrowserMultiFormatReader } = await import('@zxing/browser')
        if (gone || !video.current) return
        const reader = new BrowserMultiFormatReader()
        const controls = await reader.decodeFromConstraints({ video: { facingMode: { ideal: 'environment' } } }, video.current, (result) => {
          if (!result || done.current) return
          done.current = true
          navigator.vibrate?.(60)
          onCode(result.getText().trim())
        })
        if (gone) controls.stop()
        else {
          stop = () => controls.stop()
          setState('live')
        }
      } catch (e) {
        setState(e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError') ? 'blocked' : 'none')
      }
    })()
    return () => {
      gone = true
      stop?.()
    }
  }, [onCode])
  return (
    <div className="grid gap-3">
      <div className={cn('relative overflow-hidden rounded-lg bg-black', state === 'blocked' || state === 'none' ? 'hidden' : 'aspect-[4/3]')}>
        <video ref={video} className="size-full object-cover" muted playsInline />
        <div className="pointer-events-none absolute inset-[18%] rounded-lg border-2 border-white/80" aria-hidden />
        {state === 'starting' && <p className="absolute inset-x-0 bottom-3 text-center text-sm text-white">Starting the camera...</p>}
      </div>
      {state === 'blocked' && <p role="alert" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">The camera is blocked for this site. Allow it in the browser's site settings, or type the code below.</p>}
      {state === 'none' && <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">No camera here. Type the code below, or use a handheld scanner.</p>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) onCode(typed.trim()) }}>
        <Input aria-label="Code" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Or type the code" autoFocus={state !== 'live'} />
        <Button type="submit" variant="outline" disabled={!typed.trim()}>Find</Button>
      </form>
    </div>
  )
}

/** A button that opens the scanner. */
export function ScanButton({ onCode, title, hint, label, disabled, className }: { onCode: (code: string) => void; title?: string; hint?: string; label?: string; disabled?: boolean; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button type="button" variant="outline" size={label ? 'md' : 'icon'} className={className} disabled={disabled} aria-label={label ? undefined : title ?? 'Scan a code'} title={title ?? 'Scan a code'} onClick={() => setOpen(true)}>
        <ScanLine />{label}
      </Button>
      <ScanDialog open={open} onClose={() => setOpen(false)} onCode={onCode} title={title} hint={hint} />
    </>
  )
}
