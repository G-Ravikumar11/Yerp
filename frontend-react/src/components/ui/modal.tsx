import * as React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

const sizes = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-5xl' } as const

export interface ModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  size?: keyof typeof sizes
  footer?: React.ReactNode
  children?: React.ReactNode
}

/**
 * A dialog that rises into place and settles out again. Radix supplies the
 * focus trap, Escape and screen-reader roles; Framer Motion supplies the
 * movement, and AnimatePresence keeps the panel mounted until it has left.
 */
export function Modal({ open, onOpenChange, title, description, size = 'md', footer, children }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[3px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
              />
            </Dialog.Overlay>
            <div className="pointer-events-none fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
              <Dialog.Content
                asChild
                forceMount
                // Escape inside a sheet cell cancels that edit. It must not also close the window and lose the rest of the entry.
                onEscapeKeyDown={(e) => {
                  if ((e.target as HTMLElement | null)?.closest?.('[data-cell-editor]')) e.preventDefault()
                }}
              >
                <motion.div
                  className={cn(
                    'pointer-events-auto flex max-h-[92dvh] w-full flex-col overflow-hidden border border-border bg-popover shadow-pop',
                    'rounded-t-2xl sm:rounded-2xl',
                    sizes[size],
                  )}
                  initial={{ opacity: 0, y: 28, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 16, scale: 0.98 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 34, mass: 0.8 }}
                >
                  <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
                    <div className="min-w-0">
                      <Dialog.Title className="font-display text-lg font-semibold leading-tight">{title}</Dialog.Title>
                      <Dialog.Description
                        className={cn('mt-1 text-[13px] text-muted-foreground', !description && 'sr-only')}
                      >
                        {description ?? title}
                      </Dialog.Description>
                    </div>
                    <Dialog.Close
                      aria-label="Close"
                      className="-mr-2 -mt-1 grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      <X className="size-4" />
                    </Dialog.Close>
                  </header>
                  <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
                  {footer && (
                    <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-surface/60 px-6 py-3.5">
                      {footer}
                    </footer>
                  )}
                </motion.div>
              </Dialog.Content>
            </div>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
