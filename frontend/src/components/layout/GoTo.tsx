import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { Modal } from '@/components/ui'
import { STORE_SECTIONS, visibleNav } from '@/lib/nav'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'

type Place = { label: string; path: string; group: string }

/** Every screen this person may open - the sidebar's own list, so nothing is offered that would refuse them. */
function usePlaces(): Place[] {
  const { user, can } = useSession()
  return useMemo(() => {
    if (!user) return []
    const out: Place[] = []
    for (const e of visibleNav(can, user.type === 'employee', !!user.headOffice)) {
      if (e.kind === 'link') out.push({ label: e.label, path: e.path, group: '' })
      else for (const i of e.items) out.push({ label: i.label, path: i.path, group: e.label })
    }
    for (const s of STORE_SECTIONS) if (can(s.perm)) out.push({ label: s.label, path: s.path, group: 'Store' })
    if (user.type !== 'employee') out.push({ label: 'Settings', path: '/settings', group: '' })
    const seen = new Set<string>()
    return out.filter((p) => !seen.has(p.path) && seen.add(p.path))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])
}

/**
 * "Go to...": type part of a screen's name and press Enter - from anywhere, with Ctrl+K (Cmd+K on a Mac) or the search
 * button in the top bar. Ninety-odd screens are quicker found by name than by menu.
 */
export function GoTo() {
  const nav = useNavigate()
  const places = usePlaces()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useEffect(() => {
    if (open) {
      setQ('')
      setActive(0)
      setTimeout(() => input.current?.focus(), 0)
    }
  }, [open])

  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    const hits = places.filter((p) => words.every((w) => `${p.label} ${p.group}`.toLowerCase().includes(w)))
    // Names that start with what was typed first.
    return [...hits].sort((a, b) => Number(b.label.toLowerCase().startsWith(q.toLowerCase())) - Number(a.label.toLowerCase().startsWith(q.toLowerCase()))).slice(0, 12)
  }, [places, q])

  const go = (p: Place | undefined) => {
    if (!p) return
    setOpen(false)
    nav(p.path)
  }

  if (places.length === 0) return null
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Go to a screen (Ctrl+K)"
        className="hidden h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border border-border px-3 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:flex"
      >
        <Search className="size-4" />
        Go to...
        <kbd className="rounded border border-border px-1.5 font-mono text-[11px]">Ctrl K</kbd>
      </button>
      <button type="button" onClick={() => setOpen(true)} aria-label="Go to a screen" className="grid size-10 place-items-center rounded-lg text-muted-foreground hover:bg-accent md:hidden">
        <Search className="size-5" />
      </button>
      <Modal open={open} onOpenChange={setOpen} title="Go to" description="Type part of a screen's name, then Enter.">
        <div className="flex items-center gap-2 rounded-lg border border-input px-3">
          <Search className="size-4 text-muted-foreground" aria-hidden />
          <input
            ref={input}
            aria-label="Screen name"
            value={q}
            onChange={(e) => { setQ(e.target.value); setActive(0) }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
              if (e.key === 'Enter') { e.preventDefault(); go(shown[active]) }
            }}
            placeholder="Work orders, budgeting, payroll..."
            className="h-10 w-full bg-transparent text-sm outline-none"
          />
        </div>
        <ul role="listbox" aria-label="Screens" className="mt-3 max-h-80 overflow-y-auto">
          {shown.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No screen by that name.</li>}
          {shown.map((p, i) => (
            <li key={p.path} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => go(p)}
                className={cn('flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm', i === active ? 'bg-primary/10 text-foreground' : 'text-muted-foreground')}
              >
                <span className="font-medium text-foreground">{p.label}</span>
                {p.group && <span className="text-xs">{p.group}</span>}
              </button>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  )
}
