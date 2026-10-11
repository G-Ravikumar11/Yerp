import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CloudOff, RefreshCw } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { useOffline } from '@/stores/offline'
import { cn } from '@/lib/utils'

/**
 * Quiet while all is well. Offline, or with changes waiting to go, it says so
 * - a site engineer must never wonder whether what they entered was kept.
 */
export function SyncIndicator() {
  const { online, syncing, queue, flush, discard, retry } = useOffline()
  const [open, setOpen] = useState(false)
  const failed = queue.filter((q) => q.status === 'failed').length
  const waiting = queue.length - failed
  const show = !online || queue.length > 0

  return (
    <>
      <AnimatePresence>
        {show && (
          <motion.button
            type="button"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            onClick={() => setOpen(true)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ring-1 ring-inset transition-colors',
              failed ? 'bg-danger-soft text-danger ring-danger/25' : !online ? 'bg-warning-soft text-warning ring-warning/30' : 'bg-info-soft text-info ring-info/25',
            )}
          >
            {failed ? <AlertTriangle className="size-3.5" /> : !online ? <CloudOff className="size-3.5" /> : <RefreshCw className={cn('size-3.5', syncing && 'animate-spin')} />}
            <span className="hidden sm:inline">
              {failed ? `${failed} need attention` : !online ? (waiting ? `Offline - ${waiting} kept` : 'Offline') : `${waiting} sending`}
            </span>
            <span className="tabular sm:hidden">{queue.length || 'Off'}</span>
          </motion.button>
        )}
      </AnimatePresence>

      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Changes on this device"
        description={online ? 'Sent as soon as the connection allows, oldest first.' : 'No connection. Everything entered is kept here and goes up when it returns.'}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Close
            </Button>
            <Button onClick={() => void flush()} loading={syncing} disabled={!online || waiting === 0}>
              Send now
            </Button>
          </>
        }
      >
        {queue.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Nothing waiting. Everything has been sent.</p>
        ) : (
          <ul className="divide-y divide-border">
            {queue.map((q) => (
              <li key={q.id} className="flex items-start gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-medium">{q.label}</p>
                  <p className="text-xs text-muted-foreground">{new Date(q.createdAt).toLocaleString('en-IN')}</p>
                  {q.error && <p className="mt-1 text-xs text-danger">The server said: {q.error}</p>}
                </div>
                {q.status === 'failed' && (
                  <Button size="sm" variant="outline" onClick={() => retry(q.id)}>
                    Retry
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => discard(q.id)}>
                  Discard
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </>
  )
}
