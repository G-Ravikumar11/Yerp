import { useEffect, useRef, useState } from 'react'
import { SITE } from './data/content'
import { goTo } from './Nav'
import { asset, inr, reduceMotion } from './lib'
import { appUrl } from '@/lib/paths'

const SCOPE_OF: Record<string, string> = { electrical: 'electrical', fire: 'fire', panels: 'panels', phe: 'phe', testing: 'testing' }
const DURATION = 7000

/** The opening photograph, changing every few seconds, with the featured projects as its chapters. */
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
          <div key={s.t} className={`slide${i === cur ? ' on' : ''}`}><img src={asset(s.img)} alt={s.t} {...(i ? { loading: 'lazy' as const } : { fetchPriority: 'high' as const })} /></div>
        ))}
      </div>
      <div className="hero__shade" aria-hidden="true" />
      <div className="wrap hero__inner">
        <h1 className="hero__title">Powering India&apos;s landmarks</h1>
        <p className="hero__sub">Electrical, fire protection and plumbing contractors to India&apos;s leading developers since&nbsp;1998.</p>
        <div className="hero__cta">
          <a href="#quote" className="btn btn--primary" onClick={(e) => goTo('#quote') && e.preventDefault()}>Request a Quote</a>
          <a href="#work" className="btn btn--ghost" onClick={(e) => goTo('#work') && e.preventDefault()}>Explore Projects</a>
        </div>
      </div>
      <div className="wrap hero__chapters" id="chapters" role="tablist" aria-label="Featured projects">
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

export function Proof() {
  return (
    <section className="proof" aria-label="Company at a glance">
      <div className="wrap proof__grid">
        <p className="proof__lead">Twenty-eight years. One promise: the people who quote your job are the people who build it.</p>
        <dl className="proof__stats">
          <div><dt>Years on site</dt><Count to={28} /></div>
          <div><dt>Projects delivered</dt><Count to={1300} suffix="+" /></div>
          <div><dt>Orders in 2019–20</dt><Count to={200} prefix="₹" suffix=" Cr" /></div>
          <div><dt>Engineers &amp; crew</dt><Count to={1550} suffix="+" /></div>
        </dl>
      </div>
    </section>
  )
}

// White, background-free versions made from the original logo files (img/clients-mono).
const CLIENTS: [string, string][] = [['c27', 'L&T'], ['c46', 'Shapoorji Pallonji'], ['c31', 'NCC'], ['c18', 'My Home Group'], ['c19', 'Hyderabad Metro Rail'], ['c17', 'Punj Lloyd'],
  ['c28', 'IL&FS'], ['c32', 'Lanco'], ['c26', 'PVR Cinemas'], ['c33', 'APCRDA'], ['c34', 'APTIDCO'], ['c16', 'L&T Infotech'],
  ['c22', 'L&T Infocity'], ['c29', 'Vestian'], ['c20', 'Cybercity Builders'], ['c37', 'Indu Projects'], ['c44', 'Preston Developers'], ['c42', 'Navayuga'],
  ['c39', 'Marina Skies'], ['c41', 'Myscape'], ['c35', 'Garden City Realty'], ['c25', 'Safeway Symphony'], ['c49', 'Western Constructions'], ['c48', 'True Build Products']]

export function Clients() {
  return (
    <section className="band clients" id="clients">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Clients</p><h2 className="h2">Trusted by India&apos;s leading developers &amp; EPC majors</h2></div>
          <p className="lede">From metro rail and hospitals to IT parks and townships, the same names return to us project after project.</p>
        </div>
        <ul className="logos" id="logos" aria-label="Client logos">
          {CLIENTS.map(([f, n]) => <li key={f}><img src={asset(`site/img/clients-mono/${f}.png`)} alt={n} loading="lazy" decoding="async" /></li>)}
        </ul>
        <p className="logos__note">Selected clients from 1,300+ projects since 1998</p>
        <div className="group" id="company-group">
          <p className="eyebrow">The Yalavarti Group</p>
          <div className="group__row">
            <a href="https://www.yalavartiengineering.com/" target="_blank" rel="noopener noreferrer" className="group__item"><img src={asset('site/img/clients-mono/group-YEPL.png')} alt="Yalavarti Engineering" width="442" height="404" loading="lazy" /><span>LT Panels &amp; Cable Trays ↗</span></a>
            <a href="https://ycity.in/" target="_blank" rel="noopener noreferrer" className="group__item"><img src={asset('site/img/clients-mono/group-Ycity.png')} alt="Ycity Tech" width="836" height="282" loading="lazy" /><span>Smart Building Tech ↗</span></a>
            <div className="group__item"><img src={asset('site/img/clients-mono/group-2E.png')} alt="2e Smart Solutions" width="608" height="314" loading="lazy" /><span>Energy Efficiency</span></div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** The services: a sticky photograph that follows whichever one is in the middle of the screen. */
export function Capabilities({ scopes, toggle }: { scopes: string[]; toggle: (id: string) => void }) {
  const [active, setActive] = useState(0)
  const items = useRef<(HTMLLIElement | null)[]>([])
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(Number((e.target as HTMLElement).dataset.i))), { rootMargin: '-45% 0px -45% 0px' })
    items.current.forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [])
  return (
    <section className="band" id="capabilities">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Capabilities</p><h2 className="h2">Every system behind the walls, from one contractor</h2></div>
          <p className="lede">Electrical, fire protection, plumbing, panels and testing, designed, installed and handed over by our own crews.</p>
        </div>
        <div className="caps">
          <div className="caps__media" aria-hidden="true">
            <div className="caps__frame" id="capsframe">{SITE.services.map((s, i) => <img key={s.id} src={asset(s.img)} alt="" loading="lazy" className={i === active ? 'on' : undefined} />)}</div>
          </div>
          <ol className="caps__list" id="caps">
            {SITE.services.map((s, i) => {
              const scope = SCOPE_OF[s.id]
              const added = scope ? scopes.includes(scope) : false
              return (
                <li key={s.id} ref={(el) => { items.current[i] = el }} data-i={i} className={`cap${i === active ? ' on' : ''}`}>
                  <div className="cap__head"><span className="cap__n">0{i + 1}</span><h3>{s.title}</h3><span className="cap__tag">{s.tag}</span></div>
                  <img className="cap__img" src={asset(s.img)} alt="" loading="lazy" />
                  <div className="cap__body">
                    <p>{s.intro}</p>
                    <ul>{s.list.slice(0, 8).map((x) => <li key={x}>{x}</li>)}</ul>
                    {scope
                      ? <button className="cap__add" type="button" aria-pressed={added} onClick={() => toggle(scope)}>{added ? 'Added to Quote ✓' : 'Add to Quote +'}</button>
                      : <a className="cap__add" href="#quote" onClick={(e) => goTo('#quote') && e.preventDefault()}>Start a Quote →</a>}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </section>
  )
}

export function Work() {
  return (
    <section id="work" aria-label="Selected projects">
      <div className="wrap sechead sechead--pad sechead--split">
        <div><p className="eyebrow">Selected Work</p><h2 className="h2">Landmarks we&apos;ve powered</h2></div>
        <p className="lede">A few of the buildings, stations and townships that run on Yalavarti electrical, fire and plumbing works.</p>
      </div>
      <div id="cases">
        {SITE.featured.map((c, i) => (
          <article className="case" key={c.t}>
            <img src={asset(c.img)} alt={c.t} loading="lazy" />
            <div className="wrap case__body">
              <div><p className="case__n">0{i + 1} / 0{SITE.featured.length}</p><h3>{c.t}</h3><p>{c.d}</p></div>
              <div className="case__meta">{c.meta.map((m) => <span key={m}>{m}</span>)}</div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

export function Careers() {
  return (
    <section className="careers" aria-label="Careers">
      <img src={asset('site/img/gallery/g105.jpg')} alt="" loading="lazy" width="728" height="487" />
      <div className="wrap careers__inner">
        <p className="eyebrow">Careers</p>
        <h2 className="h2">Build the infrastructure of a growing India</h2>
        <a className="btn btn--ghost" href="https://www.yalavarti.com/current-openings.php" target="_blank" rel="noopener noreferrer">View Openings ↗</a>
      </div>
    </section>
  )
}

export function Contact() {
  return (
    <section className="band" id="contact">
      <div className="wrap">
        <p className="eyebrow">Contact</p>
        <h2 className="contact__title">Let&apos;s build together</h2>
        <div className="contact__grid">
          <a href="tel:+914040059348" className="contact__item"><span className="eyebrow">Call</span><span className="num">040 4005 9348</span></a>
          <a href="mailto:info@yalavarti.com" className="contact__item"><span className="eyebrow">Email</span>info@yalavarti.com</a>
          <a href="https://www.google.com/maps?q=Yalavarti+Projects+Kondapur+Hyderabad" target="_blank" rel="noopener noreferrer" className="contact__item"><span className="eyebrow">Corporate Office</span>Plot 1-109/21, Near RTA Office, Kondapur, Hyderabad 500084</a>
        </div>
      </div>
    </section>
  )
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap footer__top">
        <a href="#top" className="brand brand--lg" aria-label="Back to top" onClick={(e) => goTo('#top') && e.preventDefault()}><img src={asset('site/img/mark.png')} alt="" width="54" height="45" /><span translate="no">Yalavarti</span></a>
        <nav className="footer__links" aria-label="Footer">
          <a href={appUrl('login')}>YERP Login</a>
          <a href="https://www.yalavarti.com/images/pages/YPPL_PROFILE_2023.pdf" target="_blank" rel="noopener noreferrer">Company Profile (PDF)</a>
          <a href="https://www.yalavarti.com/post-your-cv.php" target="_blank" rel="noopener noreferrer">Send Your CV</a>
          <a href="https://www.linkedin.com/in/yalavartiprojects" target="_blank" rel="noopener noreferrer">LinkedIn</a>
          <a href="https://www.facebook.com/YalavartiProjectsPvtLtd" target="_blank" rel="noopener noreferrer">Facebook</a>
        </nav>
      </div>
      <div className="wrap footer__bottom">
        <p>© {new Date().getFullYear()} Yalavarti Projects Pvt. Ltd. · Engineering Consultants &amp; Contractors</p>
        <p>Hyderabad · Chennai · Bengaluru · Bhubaneswar · Noida · Nagpur · Jammu</p>
      </div>
    </footer>
  )
}
