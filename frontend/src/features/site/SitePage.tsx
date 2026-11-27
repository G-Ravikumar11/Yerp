import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import './site.css'
import { EditBar, Nav, goTo } from './Nav'
import { About, Build, Careers, Footer, Hero, Process, Story, WhatsApp } from './Sections'
import { Projects, Quality, Quote, SheetCard, sheetsFrom } from './Live'
import { reduceMotion, sitePath, useToast } from './lib'
import { isPreview, useLive, usePreviewMessages } from './siteApi'
import { ContentProvider, contentFrom, type SiteContent } from './siteContent'
import type { PageSection } from './data/content'

gsap.registerPlugin(ScrollTrigger)

const TITLE = 'Yalavarti Infra Projects | Homes, Townships & Civil Infrastructure'

/** Which sections the page draws, in order: those shown in Settings -> Website that have something to show. */
export function drawn(content: SiteContent): PageSection[] {
  const has = (id: PageSection) => id !== 'story' || content.SITE.timeline.some((m) => (m.t || m.y).trim())
  return content.SITE.layout.filter((s) => s.shown && has(s.id)).map((s) => s.id)
}

/** The company's public website: Yalavarti Infra Projects, civil engineering and construction, drawn as a drawing sheet
 *  (Look B). Besides its own words it reads its projects, openings and live figures from our records, and its enquiries
 *  land in the Tender Pipeline. At /projects: every project, with its photographs. */
export default function SitePage() {
  const root = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const [preview] = useState(isPreview)
  const messages = usePreviewMessages(preview)
  const live = useLive(preview, messages.reload)
  // The words and pictures as last published, once they arrive; the built-in copy until then. In the preview inside
  // Settings -> Website, the draft - as it is being typed.
  const content = useMemo(() => contentFrom(messages.draft ?? live?.content), [live, messages.draft])
  const [type, setType] = useState('')
  const projectsPage = /\/projects\/?$/.test(location.pathname)

  useEffect(() => {
    const seo = content.SITE.seo?.title?.trim()
    document.title = (projectsPage ? 'Projects | ' : '') + (seo || TITLE)
    document.documentElement.style.colorScheme = ''
    document.documentElement.classList.remove('dark')
  }, [content, projectsPage])

  // "Enquire about this": the enquiry opens with that kind of work chosen.
  const choose = (t: string) => {
    setType(t)
    goTo('#quote')
    const label = content.SITE.plan.types.find((x) => x.id === t)?.label
    if (label) toast.show(`${label}: tell us a little more`)
  }

  // Sections fade in as they arrive - from a visible state, so nothing is ever left hidden - and not at all for those who
  // ask for less motion.
  useLayoutEffect(() => {
    if (reduceMotion() || !root.current) return
    const ctx = gsap.context(() => {
      gsap.utils.toArray<HTMLElement>('.dtitle, .tblock, .reg, .tile, .stage, .psheet, .qs, .creds, form.enq, .jobs, .titleblock').forEach((el) =>
        gsap.from(el, { opacity: 0.35, y: 14, duration: 0.8, ease: 'power2.out', scrollTrigger: { trigger: el, start: 'top 92%', once: true } }))
    }, root)
    let rt = 0
    const refresh = () => { clearTimeout(rt); rt = window.setTimeout(() => ScrollTrigger.refresh(), 150) }
    addEventListener('load', refresh)
    void document.fonts?.ready.then(refresh)
    return () => { ctx.revert(); removeEventListener('load', refresh); clearTimeout(rt) }
  }, [projectsPage])

  const order = drawn(content)
  const numbered = order.filter((id) => id !== 'hero')
  const no = (id: PageSection) => (numbered as PageSection[]).indexOf(id) + 1
  const SECTIONS: Record<PageSection, () => React.ReactNode> = {
    hero: () => <Hero live={live} />,
    about: () => <About no={no('about')} />,
    projects: () => <Projects no={no('projects')} live={live} />,
    build: () => <Build no={no('build')} choose={choose} />,
    process: () => <Process no={no('process')} />,
    quality: () => <Quality no={no('quality')} live={live} />,
    quote: () => <Quote no={no('quote')} type={type} setType={setType} toast={toast.show} />,
    careers: () => <Careers no={no('careers')} companyId={live?.company_id} openings={live?.openings ?? []} />,
    story: () => <Story no={no('story')} />,
  }

  return (
    <ContentProvider value={content}>
      <div ref={root}>
        <a className="skip" href="#main">Skip to content</a>
        <EditBar preview={preview} />
        <Nav shown={new Set(order)} />
        <main id="main">
          {projectsPage ? <ProjectsPage live={live} /> : order.map((id) => <Fragment key={id}>{SECTIONS[id]()}</Fragment>)}
        </main>
        <Footer />
        <WhatsApp />
        <div className={`toast${toast.on ? ' on' : ''}`} role="status" aria-live="polite">{toast.text}</div>
      </div>
    </ContentProvider>
  )
}

/** Every project with photographs, each drawn as a drawing sheet with all its photographs. */
function ProjectsPage({ live }: { live: Parameters<typeof sheetsFrom>[1] }) {
  const content = contentFrom(live?.content)
  const sheets = sheetsFrom(content.SITE.sitePhotos, live)
  return (
    <section className="sec ppage" id="projects" aria-labelledby="pp-h"><div className="wrap">
      <a className="back" href={sitePath()}>← Back to the drawing</a>
      <div className="dtitle">
        <div className="no" aria-hidden="true"><span>P</span><i>Sheets</i></div>
        <h1 id="pp-h" style={{ fontSize: 'clamp(2rem,4.4vw,3.4rem)', lineHeight: 0.95 }}>Every project, with photos</h1>
        <p className="scale">Drawing sheets · photographs from site</p>
      </div>
      {sheets.length === 0 ? <p className="lede">Photographs from our sites are being added.</p> : sheets.map((s) => <SheetCard key={s.site + s.ref} s={s} all />)}
    </div></section>
  )
}
