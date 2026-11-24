import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import './site.css'
import { Nav, goTo } from './Nav'
import { Planner } from './Planner'
import { Timeline } from './Timeline'
import { About, Capabilities, Careers, Contact, Footer, Hero, HowWeBuild, Proof } from './Sections'
import { reduceMotion, useToast } from './lib'
import { Credentials, LiveProjects, QualitySafety } from './Live'
import { isPreview, useLive, usePreviewMessages } from './siteApi'
import type { PageSection } from './data/content'
import { ContentProvider, contentFrom } from './siteContent'
import { EMPTY_PLAN, typeLabel, type Plan } from './plan'

gsap.registerPlugin(ScrollTrigger)

const TITLE = 'Yalavarti Infra Projects | Homes, Townships & Civil Infrastructure'

/** The company's public front page: Yalavarti Infra Projects, civil engineering and construction. Besides its own words it
 *  reads its projects and live totals from our records, and its enquiries land in the Tender Pipeline. */
export default function SitePage() {
  const root = useRef<HTMLDivElement>(null)
  const [plan, setPlan] = useState<Plan>(EMPTY_PLAN)
  const toast = useToast()
  const [preview] = useState(isPreview)
  const messages = usePreviewMessages(preview)
  const live = useLive(preview, messages.reload)
  // The words and pictures as last published, once they arrive; the built-in copy until then. In the preview inside
  // Settings -> Website, the draft - as it is being typed.
  const content = useMemo(() => contentFrom(messages.draft ?? live?.content), [live, messages.draft])

  useEffect(() => {
    document.title = TITLE
    // Light, or dark when the visitor's device is set to dark (site.css follows the same setting).
    document.documentElement.style.colorScheme = 'light dark'
    document.documentElement.classList.remove('dark')
  }, [])

  // A "What we build" card opens the enquiry with its kind of work chosen.
  const choose = (type: string) => {
    setPlan((p) => ({ ...p, type }))
    goTo('#quote')
    toast.show(`${typeLabel(type, content.SITE.plan.types)}: tell us a little more`)
  }

  // Each section of the page, drawn in the order Settings -> Website gives them.
  const SECTIONS: Record<PageSection, () => React.ReactNode> = {
    hero: () => <Hero />,
    proof: () => <Proof live={live} />,
    about: () => <About />,
    build: () => <Capabilities choose={choose} />,
    process: () => <HowWeBuild />,
    projects: () => <LiveProjects live={live} />,
    story: () => <Timeline />,
    credentials: () => <Credentials />,
    safety: () => <QualitySafety live={live} />,
    quote: () => <Planner plan={plan} setPlan={setPlan} toast={toast.show} />,
    careers: () => <Careers companyId={live?.company_id} openings={live?.openings ?? []} />,
    contact: () => <Contact toast={toast.show} />,
  }

  // Reveals: sections fade up as they arrive.
  useLayoutEffect(() => {
    if (reduceMotion() || !root.current) return
    const ctx = gsap.context(() => {
      gsap.from(['.hero__title', '.hero__sub', '.hero__cta', '.hero__chapters'], { opacity: 0, y: 30, duration: 1.2, stagger: 0.12, ease: 'expo.out', delay: 0.1 })
      gsap.utils.toArray<HTMLElement>('.sechead, .proof__lead, .proof__stats > div, .group, .step, .contact__item, .careers__inner, .q, .brief, .live__card, .creds > div, .safety__grid > article').forEach((el) =>
        gsap.from(el, { opacity: 0, y: 32, duration: 1, ease: 'expo.out', scrollTrigger: { trigger: el, start: 'top 88%' } }))
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
    <ContentProvider value={content}>
    <div ref={root}>
      <a className="skip" href="#main">Skip to Content</a>
      <Nav />
      <main id="main">
        {content.SITE.layout.filter((s) => s.shown && SECTIONS[s.id]).map((s) => <Fragment key={s.id}>{SECTIONS[s.id]()}</Fragment>)}
      </main>
      <Footer />
      <div className={`toast${toast.on ? ' on' : ''}`} id="toast" role="status" aria-live="polite">{toast.text}</div>
    </div>
    </ContentProvider>
  )
}
