import { useEffect, useRef, useState } from 'react'
import { COMPANY, SITE, typeFor } from './data/content'
import { goTo } from './Nav'
import { asset, inr, reduceMotion } from './lib'
import { appUrl } from '@/lib/paths'
import { EnquiryForm } from './Live'
import type { Live } from './siteApi'

const DURATION = 7000
const YEAR = new Date().getFullYear()

/** The opening photograph, changing every few seconds, with the kinds of work as its chapters. */
export function Hero() {
  const [cur, setCur] = useState(0)
  const chapters = useRef<(HTMLButtonElement | null)[]>([])
  const boxRef = useRef<HTMLDivElement>(null)
  const state = useRef({ cur: 0, t0: 0, visible: true })

  const go = (i: number) => {
    const n = SITE.slides.length
    const next = (i + n) % n
    state.current.cur = next
    state.current.t0 = performance.now()
    setCur(next)
    chapters.current.forEach((b, k) => b?.style.setProperty('--p', String(k < next ? 1 : 0)))
  }

  useEffect(() => {
    const reduce = reduceMotion()
    const io = new IntersectionObserver(([e]) => { state.current.visible = e.isIntersecting })
    if (boxRef.current) io.observe(boxRef.current)
    state.current.t0 = performance.now()
    const progress = () => Number(chapters.current[state.current.cur]?.style.getPropertyValue('--p')) || 0
    const onVisible = () => { if (!document.hidden) state.current.t0 = performance.now() - progress() * DURATION }
    document.addEventListener('visibilitychange', onVisible)
    let id = 0
    const tick = (now: number) => {
      id = requestAnimationFrame(tick)
      if (reduce || !state.current.visible || document.hidden) { state.current.t0 = now - progress() * DURATION; return }
      const p = Math.min(1, (now - state.current.t0) / DURATION)
      chapters.current[state.current.cur]?.style.setProperty('--p', String(p))
      if (p >= 1) go(state.current.cur + 1)
    }
    id = requestAnimationFrame(tick)
    if (reduce) chapters.current[0]?.style.setProperty('--p', '1')
    return () => { cancelAnimationFrame(id); io.disconnect(); document.removeEventListener('visibilitychange', onVisible) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="hero" id="top" aria-label="Introduction">
      <div className="hero__slides" id="slides" ref={boxRef}>
        {SITE.slides.map((s, i) => (
          <div key={s.t} className={`slide${i === cur ? ' on' : ''}`}><img src={asset(s.img)} alt="" {...(i ? { loading: 'lazy' as const } : { fetchPriority: 'high' as const })} /></div>
        ))}
      </div>
      <div className="hero__shade" aria-hidden="true" />
      <div className="wrap hero__inner">
        <h1 className="hero__title">{SITE.hero.title}</h1>
        <p className="hero__sub">{SITE.hero.sub}</p>
        <div className="hero__cta">
          <a href="#quote" className="btn btn--primary" onClick={(e) => goTo('#quote') && e.preventDefault()}>Start a Project</a>
          <a href="#projects" className="btn btn--ghost" onClick={(e) => goTo('#projects') && e.preventDefault()}>See Our Projects</a>
        </div>
      </div>
      <div className="wrap hero__chapters" id="chapters" role="tablist" aria-label="What we build">
        {SITE.slides.map((s, i) => (
          <button key={s.t} ref={(el) => { chapters.current[i] = el }} className="chap" role="tab" aria-selected={i === cur} onClick={() => go(i)}><b>{s.t}</b><small>{s.l}</small></button>
        ))}
      </div>
    </section>
  )
}

function Count({ to, prefix = '', suffix = '' }: { to: number; prefix?: string; suffix?: string }) {
  const ref = useRef<HTMLElement>(null)
  const [text, setText] = useState(prefix + inr(to) + suffix)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return
      io.disconnect()
      const t0 = performance.now()
      const d = reduceMotion() ? 1 : 1600
      const f = (now: number) => {
        const p = Math.min(1, (now - t0) / d)
        setText(prefix + inr(to * (1 - Math.pow(1 - p, 4))) + suffix)
        if (p < 1) requestAnimationFrame(f)
      }
      requestAnimationFrame(f)
    }, { threshold: 0.6 })
    io.observe(el)
    return () => io.disconnect()
  }, [to, prefix, suffix])
  return <dd ref={ref as React.RefObject<HTMLElement>}>{text}</dd>
}

/** The company at a glance: only figures we can stand behind - the confirmed ones from content.ts and the live ones from
 *  our own project records. A figure not yet known is left out rather than guessed. */
export function Proof({ live }: { live: Live | null }) {
  const n = live?.numbers
  const stats: [string, number, string?][] = []
  if (COMPANY.founded) stats.push(['Years building', YEAR - COMPANY.founded])
  if (n?.projects_delivered) stats.push(['Projects delivered', n.projects_delivered])
  if (n?.ongoing_sites) stats.push(['Sites running now', n.ongoing_sites])
  if (COMPANY.staff) stats.push(['Engineers & crew', COMPANY.staff, '+'])
  if (n?.safe_man_hours) stats.push(['Safe man-hours', n.safe_man_hours])
  return (
    <section className="proof" aria-label="Company at a glance">
      <div className="wrap proof__grid">
        <p className="proof__lead">{SITE.lead}</p>
        {stats.length > 0 && (
          <dl className="proof__stats">
            {stats.slice(0, 4).map(([label, to, suffix]) => <div key={label}><dt>{label}</dt><Count to={to} suffix={suffix} /></div>)}
          </dl>
        )}
      </div>
    </section>
  )
}

/** Who we are, and the group company that does the building services. */
export function About() {
  return (
    <section className="band about" id="about">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">About Us</p><h2 className="h2">Civil works, start to finish</h2></div>
          <div className="about__text">{SITE.about.map((p) => <p key={p} className="lede">{p}</p>)}</div>
        </div>
        <div className="group" id="company-group">
          <p className="eyebrow">The Yalavarti Group</p>
          <p className="group__text">
            {COMPANY.group.does} on our projects and others are done by our group company,{' '}
            <a href={COMPANY.group.url} target="_blank" rel="noopener noreferrer">{COMPANY.group.name} ↗</a>
          </p>
        </div>
      </div>
    </section>
  )
}

/** What we build: a sticky photograph that follows whichever kind of work is in the middle of the screen. */
export function Capabilities({ choose }: { choose: (type: string) => void }) {
  const [active, setActive] = useState(0)
  const items = useRef<(HTMLLIElement | null)[]>([])
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(Number((e.target as HTMLElement).dataset.i))), { rootMargin: '-45% 0px -45% 0px' })
    items.current.forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [])
  return (
    <section className="band" id="build">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">What We Build</p><h2 className="h2">Homes, townships and the works around them</h2></div>
          <p className="lede">From a single house on your plot to a gated township with its roads, drains and water lines.</p>
        </div>
        <div className="caps">
          <div className="caps__media" aria-hidden="true">
            <div className="caps__frame" id="capsframe">{SITE.capabilities.map((s, i) => <img key={s.id} src={asset(s.img)} alt="" loading="lazy" className={i === active ? 'on' : undefined} />)}</div>
          </div>
          <ol className="caps__list" id="caps">
            {SITE.capabilities.map((s, i) => (
              <li key={s.id} ref={(el) => { items.current[i] = el }} data-i={i} className={`cap${i === active ? ' on' : ''}`}>
                <div className="cap__head"><span className="cap__n">0{i + 1}</span><h3>{s.title}</h3><span className="cap__tag">{s.tag}</span></div>
                <img className="cap__img" src={asset(s.img)} alt="" loading="lazy" />
                <div className="cap__body">
                  <p>{s.intro}</p>
                  <ul>{s.list.map((x) => <li key={x}>{x}</li>)}</ul>
                  <a className="cap__add" href="#quote" onClick={(e) => { e.preventDefault(); choose(typeFor(s.id)) }}>Enquire About This →</a>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}

/** How a job runs, from the land to the keys. */
export function HowWeBuild() {
  return (
    <section className="band band--light" id="process" aria-label="How we build">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">How We Build</p><h2 className="h2">From the land to the keys</h2></div>
          <p className="lede">Six stages, one team. You know who is answerable at every step.</p>
        </div>
        <ol className="steps">
          {SITE.steps.map((s, i) => (
            <li key={s.t} className="step"><span className="step__n num">0{i + 1}</span><h3>{s.t}</h3><p>{s.d}</p></li>
          ))}
        </ol>
      </div>
    </section>
  )
}

export function Careers({ companyId }: { companyId?: number }) {
  return (
    <section className="careers" id="careers" aria-label="Careers">
      <img src={asset('site/img/cat2.jpg')} alt="" loading="lazy" width="822" height="622" />
      <div className="wrap careers__inner">
        <p className="eyebrow">Careers</p>
        <h2 className="h2">Build homes and townships with us</h2>
        {/* Our own openings, from the recruitment page. Without the company's reference, a CV by email. */}
        {companyId
          ? <a className="btn btn--ghost" href={appUrl(`jobs?c=${companyId}`)}>View Openings</a>
          : <a className="btn btn--ghost" href={`mailto:${COMPANY.email}?subject=${encodeURIComponent('Job application')}`}>Send Your CV</a>}
      </div>
    </section>
  )
}

export function Contact({ toast }: { toast: (m: string) => void }) {
  const map = encodeURIComponent(COMPANY.address)
  return (
    <section className="band" id="contact">
      <div className="wrap">
        <p className="eyebrow">Contact</p>
        <h2 className="contact__title">Let&apos;s build together</h2>
        <div className="contact__grid">
          <a href={`tel:${COMPANY.phone.tel}`} className="contact__item"><span className="eyebrow">Call</span><span className="num">{COMPANY.phone.show}</span></a>
          <a href={`mailto:${COMPANY.email}`} className="contact__item"><span className="eyebrow">Email</span>{COMPANY.email}</a>
          <a href={`https://www.google.com/maps?q=${map}`} target="_blank" rel="noopener noreferrer" className="contact__item"><span className="eyebrow">Office</span>{COMPANY.address}</a>
        </div>
        <div className="contact__enq" id="enquire">
          <p className="eyebrow">Send an Enquiry</p>
          <EnquiryForm toast={toast} />
        </div>
        <iframe className="contact__map" title={`Map: ${COMPANY.name} office`} loading="lazy" referrerPolicy="no-referrer-when-downgrade"
          src={`https://www.google.com/maps?q=${map}&output=embed`} />
      </div>
    </section>
  )
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap footer__top">
        <a href="#top" className="brand brand--lg" aria-label="Back to top" onClick={(e) => goTo('#top') && e.preventDefault()}><img src={asset('site/img/mark.png')} alt="" width="54" height="54" /><span translate="no">Yalavarti Infra</span></a>
        <nav className="footer__links" aria-label="Footer">
          <a href={appUrl('terms')}>Terms of Service</a>
          <a href={appUrl('privacy')}>Privacy Policy</a>
          <a href={COMPANY.group.url} target="_blank" rel="noopener noreferrer">{COMPANY.group.name} ↗</a>
        </nav>
      </div>
      <div className="wrap footer__bottom">
        <p>© {YEAR} {COMPANY.name} · Civil Engineering &amp; Construction</p>
        <a className="footer__staff" href={appUrl('login')}>Staff login</a>
      </div>
    </footer>
  )
}
