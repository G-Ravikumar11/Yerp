import { useEffect, useState } from 'react'
import { asset, reduceMotion } from './lib'
import { appUrl } from '@/lib/paths'

const LINKS: [string, string][] = [['capabilities', 'Capabilities'], ['work', 'Projects'], ['clients', 'Clients'], ['company', 'Company'], ['contact', 'Contact']]
const WATCHED = ['capabilities', 'work', 'projects', 'clients', 'company', 'quote', 'contact']

/** Scroll to a section and keep the address bar in step, as the page's own links do. */
export function goTo(id: string) {
  const el = id.length > 1 ? document.getElementById(id.slice(1)) : null
  if (id === '#top') scrollTo({ top: 0, behavior: reduceMotion() ? 'auto' : 'smooth' })
  else if (el) el.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' })
  else return false
  history.replaceState(null, '', id === '#top' ? location.pathname : id)
  return true
}

/** The top bar: clear over the photographs, solid once scrolled, hidden while reading downwards. */
export function Nav() {
  const [open, setOpen] = useState(false)
  const [solid, setSolid] = useState(false)
  const [hide, setHide] = useState(false)
  const [progress, setProgress] = useState(0)
  const [active, setActive] = useState('')

  useEffect(() => {
    let lastY = 0
    const onScroll = () => {
      const y = scrollY
      const heroH = innerHeight * 0.85
      setSolid(y > heroH - 80)
      // Worked out now: the updater below runs later, after lastY has moved on.
      const up = y < lastY - 4
      const down = y > heroH && y > lastY + 4
      setHide((h) => (open || up ? false : down ? true : h))
      lastY = y
      const max = document.documentElement.scrollHeight - innerHeight
      setProgress(max > 0 ? y / max : 0)
    }
    addEventListener('scroll', onScroll, { passive: true })
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    addEventListener('keydown', onKey)
    return () => {
      removeEventListener('scroll', onScroll)
      removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: '-45% 0px -50% 0px' })
    WATCHED.forEach((id) => {
      const el = document.getElementById(id)
      if (el) io.observe(el)
    })
    return () => io.disconnect()
  }, [])

  const click = (e: React.MouseEvent, id: string) => {
    if (goTo(id)) {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <header className={`nav${solid ? ' solid' : ''}${hide && !open ? ' hide' : ''}${open ? ' open' : ''}`} id="nav" style={{ ['--p' as string]: progress.toFixed(4) }}>
      <a href="#top" className="brand" aria-label="Yalavarti Projects, home" onClick={(e) => click(e, '#top')}>
        <img src={asset('site/img/mark.png')} alt="" width="36" height="30" />
        <span translate="no">Yalavarti</span>
      </a>
      <nav className="nav__links" id="navlinks" aria-label="Primary">
        {LINKS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className={active === id ? 'active' : undefined} aria-current={active === id ? 'true' : undefined} onClick={(e) => click(e, `#${id}`)}>{label}</a>
        ))}
        <a href="#quote" className="nav__m nav__m--quote" onClick={(e) => click(e, '#quote')}>Request a Quote</a>
      </nav>
      <a href={appUrl('login')} className="btn btn--login btn--sm nav__login" title="Sign in to YERP, the Yalavarti ERP">
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
        YERP Login
      </a>
      <a href="#quote" className="btn btn--primary btn--sm nav__cta" onClick={(e) => click(e, '#quote')}>Request a Quote</a>
      <button className="nav__burger" id="burger" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} aria-controls="navlinks" onClick={() => setOpen((o) => !o)}><span /><span /></button>
    </header>
  )
}
