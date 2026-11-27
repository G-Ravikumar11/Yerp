import { useEffect, useRef, useState } from 'react'

/** A file under public/site, as the browser must ask for it (the app lives under /next/). */
export const asset = (path: string) => import.meta.env.BASE_URL + path

/** A picture named in the website's content: one of the site's own files (site/img/...), or one uploaded from
 *  Settings -> Website, which the server keeps (/api/public/site/images/...). */
export const imgSrc = (path: string) => (path.startsWith('/api/') ? (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '') + path : asset(path))

/** An address of the company website itself: "/" and "/projects" when built; in development the staff app owns "/", and
 *  the site is under /site. */
export const sitePath = (page = '') => (import.meta.env.PROD ? '/' : '/site/') + page.replace(/^\//, '')

export const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export const inr = (n: number) => new Intl.NumberFormat('en-IN').format(Math.round(n))

/** True once the element has come near the screen. Used to start the 3D scenes only when they are about to be seen. */
export function useNear<E extends HTMLElement>(margin = '700px 0px') {
  const ref = useRef<E>(null)
  const [near, setNear] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        setNear(true)
        io.disconnect()
      }
    }, { rootMargin: margin })
    io.observe(el)
    return () => io.disconnect()
  }, [margin])
  return [ref, near] as const
}

/** A short message at the foot of the page. */
export function useToast() {
  const [text, setText] = useState('')
  const [on, setOn] = useState(false)
  const timer = useRef<number>(0)
  const show = (m: string) => {
    setText(m)
    setOn(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOn(false), 2400)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return { text, on, show }
}
