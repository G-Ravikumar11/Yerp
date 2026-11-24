import { useEffect, useRef, useState } from 'react'
import { typeFor } from './data/content'
import { useContent } from './siteContent'
import { goTo } from './Nav'
import { asset, imgSrc, inr, reduceMotion } from './lib'
import { Head } from './Head'
import { appUrl } from '@/lib/paths'
import { EnquiryForm } from './Live'
import type { Live, Opening } from './siteApi'

const DURATION = 7000
const YEAR = new Date().getFullYear()

/** The opening photograph, changing every few seconds, with the kinds of work as its chapters. */
export function Hero() {
  const { SITE } = useContent()
  // The slides can change once the published content arrives; the timer below reads the count from here.
  const count = useRef(SITE.slides.length)
  count.current = SITE.slides.length
  const [cur, setCur] = useState(0)
  const chapters = useRef<(HTMLButtonElement | null)[]>([])
  const boxRef = useRef<HTMLDivElement>(null)
  const state = useRef({ cur: 0, t0: 0, visible: true })

  const go = (i: number) => {
    const n = count.current
    if (!n) return
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
          <div key={s.t} className={`slide${i === cur ? ' on' : ''}`}><img src={imgSrc(s.img)} alt="" {...(i ? { loading: 'lazy' as const } : { fetchPriority: 'high' as const })} /></div>
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
  const { COMPANY, SITE } = useContent()
  const n = live?.numbers
  const stats: [string, number, string?][] = []
  if (COMPANY.founded) stats.push(['Years building', YEAR - COMPANY.founded])
  if (n?.projects_delivered) stats.push(['Projects delivered', n.projects_delivered])
  // The sites we list on the page are all running (Hemanth, 19 Nov 2026), so the count never shows fewer than them.
  const running = Math.max(n?.ongoing_sites ?? 0, SITE.sites.reduce((k, g) => k + g.names.length, 0))
  if (running) stats.push(['Sites running now', running])
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
  const { COMPANY, SITE } = useContent()
  return (
    <section className="band about" id="about">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">{SITE.headings.about.eyebrow}</p><h2 className="h2">{SITE.headings.about.title}</h2></div>
          <div className="about__text">{SITE.about.map((p) => <p key={p} className="lede">{p}</p>)}</div>
        </div>
        <div className="group" id="company-group">
          <p className="eyebrow">The Yalavarti Group</p>
          <p className="group__text">
            For {COMPANY.group.does}, see our group company,{' '}
            <a href={COMPANY.group.url} target="_blank" rel="noopener noreferrer">{COMPANY.group.name} ↗</a>
          </p>
        </div>
      </div>
    </section>
  )
}

/** What we build: a sticky photograph that follows whichever kind of work is in the middle of the screen. */
export function Capabilities({ choose }: { choose: (type: string) => void }) {
  const { SITE } = useContent()
  const [active, setActive] = useState(0)
  const items = useRef<(HTMLLIElement | null)[]>([])
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(Number((e.target as HTMLElement).dataset.i))), { rootMargin: '-45% 0px -45% 0px' })
    items.current.forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [SITE.capabilities.length])
  return (
    <section className="band" id="build">
      <div className="wrap">
        <Head h={SITE.headings.build} />
        <div className="caps">
          <div className="caps__media" aria-hidden="true">
            <div className="caps__frame" id="capsframe">{SITE.capabilities.map((s, i) => <img key={s.id} src={imgSrc(s.img)} alt="" loading="lazy" className={i === active ? 'on' : undefined} />)}</div>
          </div>
          <ol className="caps__list" id="caps">
            {SITE.capabilities.map((s, i) => (
              <li key={s.id} ref={(el) => { items.current[i] = el }} data-i={i} className={`cap${i === active ? ' on' : ''}`}>
                <div className="cap__head"><span className="cap__n">0{i + 1}</span><h3>{s.title}</h3><span className="cap__tag">{s.tag}</span></div>
                <img className="cap__img" src={imgSrc(s.img)} alt="" loading="lazy" />
                <div className="cap__body">
                  <p>{s.intro}</p>
                  <ul>{s.list.map((x) => <li key={x}>{x}</li>)}</ul>
                  <a className="cap__add" href="#quote" onClick={(e) => { e.preventDefault(); choose(typeFor(s.id, SITE.plan.types)) }}>Enquire About This →</a>
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
  const { SITE } = useContent()
  return (
    <section className="band band--light" id="process" aria-label="How we build">
      <div className="wrap">
        <Head h={SITE.headings.process} />
        <ol className="steps">
          {SITE.steps.map((s, i) => (
            <li key={s.t} className="step"><span className="step__n num">0{i + 1}</span><h3>{s.t}</h3><p>{s.d}</p></li>
          ))}
        </ol>
      </div>
    </section>
  )
}

/** Our openings, posted from Settings -> Website or from Recruitment. "Apply" opens the opening's own application form,
 *  which lands in Recruitment. With none open, a CV by email. */
export function Careers({ companyId, openings }: { companyId?: number; openings: Opening[] }) {
  const { COMPANY, SITE } = useContent()
  const h = SITE.headings.careers
  const cv = `mailto:${COMPANY.email}?subject=${encodeURIComponent('Job application')}`
  return (
    <section className="careers" id="careers" aria-label="Careers">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">{h.eyebrow}</p><h2 className="h2">{h.title}</h2></div>
          <p className="lede">{h.lede || (openings.length ? 'Engineers, supervisors and crew for our sites. Apply online - it takes a few minutes.' : 'No openings right now. Send us your CV and we will keep it for the next one.')}</p>
        </div>
        {openings.length > 0 && (
          <ul className="jobs" aria-label="Openings">
            {openings.map((o) => (
              <li key={o.id} className="job">
                <div className="job__text">
                  <h3>{o.title}</h3>
                  {(o.location || o.experience) && <p className="job__meta">{[o.location, o.experience && `${o.experience} experience`].filter(Boolean).join(' · ')}</p>}
                  {o.description && <p className="job__desc">{o.description}</p>}
                </div>
                {o.apply_token
                  ? <a className="btn btn--light" href={appUrl(`apply?token=${encodeURIComponent(o.apply_token)}`)} aria-label={`Apply for ${o.title}`}>Apply</a>
                  : <a className="btn btn--outline-light" href={cv}>Send Your CV</a>}
              </li>
            ))}
          </ul>
        )}
        <div className="careers__more">
          {openings.length > 0 && companyId ? <a className="link-arrow" href={appUrl(`jobs?c=${companyId}`)}>Every opening, with the full details →</a> : null}
          <a className={openings.length ? 'link-arrow' : 'btn btn--light'} href={cv}>{openings.length ? 'Or send us your CV →' : 'Send Your CV'}</a>
        </div>
      </div>
    </section>
  )
}

export function Contact({ toast }: { toast: (m: string) => void }) {
  const { COMPANY, SITE } = useContent()
  const map = encodeURIComponent(COMPANY.address)
  return (
    <section className="band" id="contact">
      <div className="wrap">
        <p className="eyebrow">{SITE.headings.contact.eyebrow}</p>
        <h2 className="contact__title">{SITE.headings.contact.title}</h2>
        {SITE.headings.contact.lede && <p className="lede">{SITE.headings.contact.lede}</p>}
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
  const { COMPANY, SITE } = useContent()
  return (
    <footer className="footer">
      <div className="wrap footer__top">
        <a href="#top" className="brand brand--lg" aria-label="Back to top" onClick={(e) => goTo('#top') && e.preventDefault()}><img src={asset('site/img/mark.png')} alt="" width="54" height="54" /><span translate="no">Yalavarti Infra</span></a>
        <nav className="footer__links" aria-label="Footer">
          {SITE.footer.showGroupLink && <a href={COMPANY.group.url} target="_blank" rel="noopener noreferrer">{COMPANY.group.name} ↗</a>}
        </nav>
      </div>
      <div className="wrap footer__bottom">
        <p>© {YEAR} {COMPANY.name}{SITE.footer.tagline ? ` · ${SITE.footer.tagline}` : ''}</p>
        <a className="footer__staff" href={appUrl('login')}>Staff login</a>
      </div>
    </footer>
  )
}
