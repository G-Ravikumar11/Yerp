import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import './site.css'
import { Atlas } from './Atlas'
import { Nav } from './Nav'
import { Planner } from './Planner'
import { Systems } from './Systems'
import { Timeline } from './Timeline'
import { Capabilities, Careers, Clients, Contact, Footer, Hero, Proof, Work } from './Sections'
import { reduceMotion, useToast } from './lib'
import { EMPTY_PLAN, scopeLabel, type Plan } from './plan'

gsap.registerPlugin(ScrollTrigger)

const TITLE = 'Yalavarti Projects | Electrical, Fire & PHE Contractors, Hyderabad'

/** The company's public front page. The only thing here that is not content is the quote brief, which leaves as an email. */
export default function SitePage() {
  const root = useRef<HTMLDivElement>(null)
  const [plan, setPlan] = useState<Plan>(EMPTY_PLAN)
  const toast = useToast()

  useEffect(() => {
    document.title = TITLE
    document.documentElement.style.colorScheme = 'dark'
  }, [])

  const toggleScope = (id: string) => {
    const on = !plan.scopes.includes(id)
    setPlan((p) => ({ ...p, scopes: on ? [...p.scopes, id] : p.scopes.filter((s) => s !== id) }))
    toast.show(on ? `${scopeLabel(id)} added to your quote` : `${scopeLabel(id)} removed from your quote`)
  }

  // Reveals: sections fade up as they arrive, and each project band tilts flat as it fills the screen.
  useLayoutEffect(() => {
    if (reduceMotion() || !root.current) return
    const ctx = gsap.context(() => {
      gsap.from(['.hero__title', '.hero__sub', '.hero__cta', '.hero__chapters'], { opacity: 0, y: 30, duration: 1.2, stagger: 0.12, ease: 'expo.out', delay: 0.1 })
      gsap.utils.toArray<HTMLElement>('.sechead, .proof__lead, .proof__stats > div, .case__body, .group, .contact__item, .careers__inner, .q, .brief').forEach((el) =>
        gsap.from(el, { opacity: 0, y: 32, duration: 1, ease: 'expo.out', scrollTrigger: { trigger: el, start: 'top 88%' } }))
      gsap.utils.toArray<HTMLElement>('.case').forEach((c) =>
        gsap.fromTo(c, { rotateX: 14, scale: 0.88, transformPerspective: 1400, transformOrigin: '50% 0%' }, { rotateX: 0, scale: 1, ease: 'none', scrollTrigger: { trigger: c, start: 'top bottom', end: 'top 35%', scrub: true } }))
      gsap.from('#logos li', { opacity: 0, y: 16, duration: 0.7, stagger: 0.025, ease: 'power3.out', scrollTrigger: { trigger: '#logos', start: 'top 85%' } })
    }, root)
    // Recompute trigger positions whenever fonts or late images change the page height.
    let rt = 0
    const refresh = () => { clearTimeout(rt); rt = window.setTimeout(() => ScrollTrigger.refresh(), 150) }
    addEventListener('load', refresh)
    void document.fonts?.ready.then(refresh)
    let lastH = 0
    const ro = new ResizeObserver(() => { const h = document.body.scrollHeight; if (Math.abs(h - lastH) > 4) { lastH = h; refresh() } })
    ro.observe(root.current)
    return () => { ctx.revert(); removeEventListener('load', refresh); ro.disconnect(); clearTimeout(rt) }
  }, [])

  return (
    <div ref={root}>
      <a className="skip" href="#main">Skip to Content</a>
      <Nav />
      <main id="main">
        <Hero />
        <Proof />
        <Clients />
        <Capabilities scopes={plan.scopes} toggle={toggleScope} />
        <Systems scopes={plan.scopes} toggle={toggleScope} />
        <Work />
        <Atlas />
        <Timeline />
        <Planner plan={plan} setPlan={setPlan} toggleScope={toggleScope} toast={toast.show} />
        <Careers />
        <Contact />
      </main>
      <Footer />
      <div className={`toast${toast.on ? ' on' : ''}`} id="toast" role="status" aria-live="polite">{toast.text}</div>
    </div>
  )
}
