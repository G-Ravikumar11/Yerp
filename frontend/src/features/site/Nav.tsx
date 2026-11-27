import { useEffect, useState } from 'react'
import { appUrl } from '@/lib/paths'
import { asset, reduceMotion } from './lib'
import { useContent } from './siteContent'
import { apiPath } from './siteApi'
import type { PageSection } from './data/content'

/** Scroll to a section and keep the address bar in step, as the page's own links do. */
export function goTo(id: string) {
  const el = id.length > 1 ? document.getElementById(id.slice(1)) : null
  if (id === '#top') scrollTo({ top: 0, behavior: reduceMotion() ? 'auto' : 'smooth' })
  else if (el) el.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' })
  else return false
  history.replaceState(null, '', id === '#top' ? location.pathname : id)
  return true
}

/** The sections the menu links to, in the menu's order. "Contact" is the enquiry section's. */
const MENU: PageSection[] = ['projects', 'build', 'process', 'quality', 'careers', 'quote']

/** For whoever may edit the website, signed in: a bar to the panel, with when it was last published. Nobody else sees it,
 *  and it is never in the panel's own preview. */
export function EditBar({ preview }: { preview: boolean }) {
  const [info, setInfo] = useState<{ can_edit: boolean; last_published: string } | null>(null)
  useEffect(() => {
    if (preview) return
    let gone = false
    fetch(apiPath('/api/website/editor'), { credentials: 'include' }).then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!gone && d?.can_edit) setInfo(d) }).catch(() => undefined)
    return () => { gone = true }
  }, [preview])
  if (!info) return null
  const when = info.last_published ? new Date(info.last_published.replace(' ', 'T')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''
  return (
    <div className="editbar" role="region" aria-label="Edit the website">
      <div className="wrap"><a href={appUrl('website')}>Edit website</a>{when && <span>· last published {when}</span>}</div>
    </div>
  )
}

/** Paper (light) or blueprint (dark): the visitor's own choice, kept on this device, else their device's setting. */
function useTheme() {
  const dark = () => {
    const t = document.documentElement.getAttribute('data-theme')
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  }
  const [isDark, setDark] = useState(dark)
  const flip = () => {
    const next = dark() ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try { localStorage.setItem('yip-theme', next) } catch { /* private window: this visit only */ }
    setDark(next === 'dark')
  }
  return { isDark, flip }
}

/** The blue strip: what we do, where, the phone, and the paper / blueprint switch. Then the menu bar. */
export function Nav({ shown }: { shown: Set<PageSection> }) {
  const { COMPANY, SITE } = useContent()
  const { isDark, flip } = useTheme()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState('')
  const links = MENU.filter((id) => shown.has(id)).map((id) => [id, SITE.headings[id as Exclude<PageSection, 'hero'>]?.eyebrow ?? id] as const)

  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: '-45% 0px -50% 0px' })
    MENU.forEach((id) => { const el = document.getElementById(id); if (el) io.observe(el) })
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    addEventListener('keydown', onKey)
    return () => { io.disconnect(); removeEventListener('keydown', onKey) }
  }, [shown])

  const click = (e: React.MouseEvent, id: string) => {
    if (goTo(id)) { e.preventDefault(); setOpen(false) }
  }
  return (
    <>
      <div className="strip"><div className="wrap">
        <span>{COMPANY.trade}</span>
        {COMPANY.regions && <span className="hide-s">{COMPANY.regions}</span>}
        <span className="r">
          {COMPANY.phone.show && <a href={`tel:${COMPANY.phone.tel}`} className="hide-s num">{COMPANY.phone.show}</a>}
          <button type="button" onClick={flip} aria-label={isDark ? 'Switch to the paper (light) look' : 'Switch to the blueprint (dark) look'}>{isDark ? 'Paper' : 'Blueprint'}</button>
        </span>
      </div></div>
      <header className="nav" id="nav">
        <div className="wrap">
          <a className="brand" href="#top" aria-label={`${COMPANY.name}, home`} onClick={(e) => click(e, '#top')}>
            <img src={asset('site/img/mark.png')} alt="" width="38" height="38" />
            <span><b translate="no">Yalavarti Infra</b><small>Civil · Hyderabad</small></span>
          </a>
          <nav className="links" aria-label="Primary">
            {links.map(([id, label]) => <a key={id} href={`#${id}`} aria-current={active === id ? 'true' : undefined} onClick={(e) => click(e, `#${id}`)}>{label}</a>)}
          </nav>
          {shown.has('quote') && <a className="btn btn--solid" href="#quote" onClick={(e) => click(e, '#quote')}>Request a quote</a>}
          <button className="menu" type="button" aria-expanded={open} aria-controls="mpanel" onClick={() => setOpen((o) => !o)}>{open ? 'Close' : 'Menu'}</button>
        </div>
        {open && (
          <nav className="mpanel" id="mpanel" aria-label="Menu"><div className="wrap">
            {links.map(([id, label]) => <a key={id} href={`#${id}`} onClick={(e) => click(e, `#${id}`)}>{label}</a>)}
            {shown.has('quote') && <a className="btn btn--solid" href="#quote" onClick={(e) => click(e, '#quote')}>Request a quote</a>}
          </div></nav>
        )}
      </header>
    </>
  )
}
