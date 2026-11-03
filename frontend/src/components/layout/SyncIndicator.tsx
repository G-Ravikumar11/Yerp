import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CloudOff, RefreshCw } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { personKey } from '@/lib/session'
import { isMine, useOffline } from '@/stores/offline'
import { cn } from '@/lib/utils'

/**
 * Quiet while all is well. Offline, or with changes waiting to go, it says so
 * - a site engineer must never wonder whether what they entered was kept.
 * Each change can be sent again or removed; a change that somebody else saved over meanwhile asks whose version stands.
 * On a shared phone, what another person entered stays theirs: it is listed, but only they can send or remove it.
 */
export function SyncIndicator({ className }: { className?: string }) {
  const { online, syncing, queue, flush, discard, retry, keepMine } = useOffline()
  const [open, setOpen] = useState(false)
  const me = personKey()
  const mine = queue.filter((q) => isMine(q, me))
  const others = queue.filter((q) => !isMine(q, me))
  const conflicts = mine.filter((q) => q.status === 'conflict').length
  const failed = mine.filter((q) => q.status === 'failed').length
  const waiting = mine.length - failed - conflicts
  const attention = failed + conflicts
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
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ring-1 ring-inset transition-colors',
              attention ? 'bg-danger-soft text-danger ring-danger/25' : !online ? 'bg-warning-soft text-warning ring-warning/30' : 'bg-info-soft text-info ring-info/25',
              className,
            )}
          >
            {attention ? <AlertTriangle className="size-3.5" /> : !online ? <CloudOff className="size-3.5" /> : <RefreshCw className={cn('size-3.5', syncing && 'animate-spin')} />}
            <span className="hidden sm:inline">
              {attention ? `${attention} need${attention === 1 ? 's' : ''} attention` : !online ? (waiting ? `Offline - ${waiting} kept` : 'Offline') : waiting ? `${waiting} sending` : `${others.length} waiting for others`}
            </span>
            <span className="tabular sm:hidden">{attention || waiting || others.length || 'Off'}</span>
          </motion.button>
        )}
      </AnimatePresence>

      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Changes on this phone"
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
            {mine.map((q) => (
              <li key={q.id} className="py-3">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-medium">{q.label}</p>
                    <p className="text-xs text-muted-foreground">{new Date(q.createdAt).toLocaleString('en-IN')}</p>
                    {q.status === 'conflict' && <p className="mt-1 text-xs text-warning">Somebody else saved this while you were away from signal. Choose whose version stands.</p>}
                    {q.status === 'failed' && q.error && <p className="mt-1 text-xs text-danger">The server said: {q.error}</p>}
                  </div>
                  {q.status === 'failed' && (
                    <Button size="sm" variant="outline" onClick={() => retry(q.id)}>
                      Retry
                    </Button>
                  )}
                  {q.status !== 'conflict' && (
                    <Button size="sm" variant="ghost" onClick={() => discard(q.id)}>
                      Remove
                    </Button>
                  )}
                </div>
                {q.status === 'conflict' && (
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => keepMine(q.id)}>
                      Keep mine
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => discard(q.id)}>
                      Take theirs
                    </Button>
                  </div>
                )}
              </li>
            ))}
            {others.map((q) => (
              <li key={q.id} className="py-3 opacity-70">
                <p className="text-[13.5px] font-medium">{q.label}</p>
                <p className="text-xs text-muted-foreground">Waiting for {q.byName || 'the person who made it'} to sign in. It is theirs to send.</p>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </>
  )
}
