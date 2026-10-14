import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/** A value that follows another after it has settled - so a search box asks the server once, not per keystroke. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return settled
}

/** True at and above a CSS pixel width - to pick a layout, not just to style one. */
export function useMinWidth(px: number): boolean {
  const query = `(min-width: ${px}px)`
  const [matches, setMatches] = useState(() => typeof matchMedia !== 'undefined' && matchMedia(query).matches)
  useEffect(() => {
    const mq = matchMedia(query)
    const on = () => setMatches(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [query])
  return matches
}

/**
 * Open a register's "new" form when the page is arrived at with ?new=1 - the HO portal's
 * "Open a vendor code" lands on Sub Contract Registration with the form already up. Only when
 * `allowed`: a person without the right sees the register, not a form they would be refused at.
 */
export function useOpenOnArrival(open: () => void, allowed: boolean) {
  const [params, setParams] = useSearchParams()
  const asked = params.get('new') === '1'
  useEffect(() => {
    // Not yet allowed may be not yet known (the session still loading): wait rather than drop the ask.
    if (!asked || !allowed) return
    open()
    const next = new URLSearchParams(params)
    next.delete('new')
    setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked, allowed])
}
