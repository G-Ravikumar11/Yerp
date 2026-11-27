import { appUrl } from '@/lib/paths'
import { typeFor } from './data/content'
import { DTitle, waNumber } from './Parts'
import { goTo } from './Nav'
import { asset, imgSrc, inr } from './lib'
import { useContent } from './siteContent'
import type { Live, Opening } from './siteApi'

const YEAR = new Date().getFullYear()

/** The figures the title block can show, in the brief's order of priority: sites running, towns, years, engineers and crew,
 *  then states and kinds of work. Only figures we have; at most four. */
export function figures(live: Live | null, site: ReturnType<typeof useContent>['SITE'], company: ReturnType<typeof useContent>['COMPANY']) {
  const rows = site.sites.filter((r) => r.site.trim())
  const listed = rows.filter((r) => /ongoing|running/i.test(r.status)).length
  const recorded = live?.numbers.ongoing_sites ?? 0
  const towns = new Set(rows.map((r) => r.town.trim().toLowerCase()).filter(Boolean)).size
  const states = new Set(rows.map((r) => r.state.trim().toUpperCase()).filter(Boolean)).size
  const kinds = site.capabilities.filter((c) => c.title.trim()).length
  const out: { label: string; value: number; live?: boolean }[] = []
  const running = Math.max(listed, recorded)
  if (running) out.push({ label: 'Sites running now', value: running, live: recorded > 0 && recorded >= listed })
  if (towns) out.push({ label: 'Towns', value: towns })
  if (company.founded) out.push({ label: 'Years building', value: YEAR - company.founded })
  if (company.staff) out.push({ label: 'Engineers & crew', value: company.staff })
  if (states) out.push({ label: 'States', value: states })
  if (kinds) out.push({ label: 'Kinds of work', value: kinds })
  return out.slice(0, 4)
}

/** The opening: kicker, headline, the two buttons, the site photograph framed with dimension lines and its callout, the
 *  figures in a title block, and who we build for. */
export function Hero({ live }: { live: Live | null }) {
  const { COMPANY, SITE } = useContent()
  const h = SITE.hero
  const photo = h.photo
  const figs = figures(live, SITE, COMPANY)
  const clients = SITE.clients.map((c) => c.trim()).filter(Boolean)
  return (
    <section className="hero" id="top" aria-label="Introduction"><div className="wrap">
      <div className={`hero__grid${photo.img ? '' : ' hero__grid--solo'}`}>
        <div>
          {h.kicker && <p className="kicker">{h.kicker}</p>}
          <h1>{h.title}{h.accent && <> <em>{h.accent}</em></>}</h1>
          {h.sub && <p className="sub">{h.sub}</p>}
          <div className="ctas">
            <a className="btn btn--solid" href="#projects" onClick={(e) => goTo('#projects') && e.preventDefault()}>See our projects <span className="arrow" aria-hidden="true">→</span></a>
            <a className="btn btn--line" href="#quote" onClick={(e) => goTo('#quote') && e.preventDefault()}>Request a quote</a>
          </div>
        </div>
        {photo.img && (
          <figure className="frame">
            {photo.label && <div className="dim t" aria-hidden="true"><span>{photo.label}</span></div>}
            {photo.side && <div className="dim l" aria-hidden="true"><span>{photo.side}</span></div>}
            <img src={imgSrc(photo.img)} alt={[photo.label, photo.side, photo.callout].filter(Boolean).join(': ')} width="1200" height="825" fetchPriority="high" />
            {photo.callout && <figcaption className="callout">{photo.calloutTitle && <b>{photo.calloutTitle}</b>}{photo.callout}</figcaption>}
          </figure>
        )}
      </div>
      {(figs.length > 0 || h.note) && (
        <dl className="tblock" aria-label="At a glance" style={{ ['--n' as string]: figs.length }}>
          {figs.map((f) => (
            <div key={f.label}>
              <dt><small>{f.label}</small></dt>
              <dd className="num">{inr(f.value)}</dd>
              {f.live && <small className="live">Live from site records</small>}
            </div>
          ))}
          {(h.noteTitle || h.note) && <div className="note">{h.noteTitle && <b>{h.noteTitle}</b>}{h.note}</div>}
        </dl>
      )}
      {clients.length > 0 && <div className="clients"><small>Building for</small>{clients.map((c) => <span key={c}>{c}</span>)}</div>}
    </div></section>
  )
}

/** About: our general notes, with the group company in a "Ref." box. */
export function About({ no }: { no: number }) {
  const { COMPANY, SITE } = useContent()
  const notes = SITE.about.map((p) => p.trim()).filter(Boolean)
  const g = COMPANY.group
  return (
    <section className="sec" id="about" aria-labelledby="about-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.about} id="about-h" />
      <div className="notes">
        <div>
          <h3>General notes</h3>
          <ol>{notes.map((p) => <li key={p}>{p}</li>)}</ol>
        </div>
        {g.name && (
          <aside className="group" aria-label="The Yalavarti Group">
            <b>Part of the Yalavarti Group</b>
            <p>For {g.does || 'building services'}, see our group company, {g.name}.</p>
            {g.url && <a href={g.url} target="_blank" rel="noopener noreferrer">{g.url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')} ↗</a>}
          </aside>
        )}
      </div>
    </div></section>
  )
}

/** What we build: detail tiles, numbered 3.1, 3.2... The first is twice as wide; a kind of work marked as a line (civil
 *  structures) is a line under the grid. "Enquire about this" opens the enquiry with that kind of work chosen. */
export function Build({ no, choose }: { no: number; choose: (type: string) => void }) {
  const { SITE } = useContent()
  const all = SITE.capabilities.filter((c) => c.title.trim())
  const tiles = all.filter((c) => !c.line)
  const lines = all.filter((c) => c.line)
  return (
    <section className="sec" id="build" aria-labelledby="build-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.build} id="build-h" />
      <div className="tiles">
        {tiles.map((c, i) => (
          <article key={c.id || c.title} className={`tile${i === 0 && tiles.length > 2 ? ' tile--wide' : ''}`}>
            <div className="ph">
              {c.img ? <img src={imgSrc(c.img)} alt={c.title} loading="lazy" decoding="async" width="600" height="400" /> : <img src={asset('site/img/mark.png')} alt="" loading="lazy" style={{ objectFit: 'contain', padding: '20%' }} />}
              <span className="tag">Detail {no}.{i + 1}</span>
            </div>
            <div className="body">
              <h3>{c.title}</h3>
              {c.intro && <p>{c.intro}</p>}
              {c.list.length > 0 && <ul>{c.list.filter(Boolean).map((x) => <li key={x}>{x}</li>)}</ul>}
              <a className="ask" href="#quote" onClick={(e) => { e.preventDefault(); choose(typeFor(c.id, SITE.plan.types)) }}>Enquire about this →</a>
            </div>
          </article>
        ))}
      </div>
      {lines.map((c, i) => (
        <p key={c.id || c.title} className="tiles__also">Also: <b>{c.title.toLowerCase()}</b>{c.intro ? `, ${c.intro.replace(/\.$/, '')}` : ''} (detail {no}.{tiles.length + i + 1}).</p>
      ))}
    </div></section>
  )
}

/** How we build: the stages on a chainage line, the last marked in red. */
export function Process({ no }: { no: number }) {
  const { SITE } = useContent()
  const steps = SITE.steps.filter((s) => s.t.trim())
  return (
    <section className="sec sec--tint" id="process" aria-labelledby="process-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.process} id="process-h" />
      <ol className="chain" style={{ ['--n' as string]: steps.length }}>
        {steps.map((s, i) => <li key={s.t} className="stage"><span className="ch">Stage {i + 1}</span><h3>{s.t}</h3>{s.d && <p>{s.d}</p>}</li>)}
      </ol>
    </div></section>
  )
}

/** Our story: the milestones on a chainage line with their years. Left off while there are none. */
export function Story({ no }: { no: number }) {
  const { SITE } = useContent()
  const ms = SITE.timeline.filter((m) => m.t.trim() || m.y.trim())
  if (!ms.length) return null
  return (
    <section className="sec" id="story" aria-labelledby="story-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.story} id="story-h" />
      <ol className="chain" style={{ ['--n' as string]: Math.min(ms.length, 6) }}>
        {ms.map((m) => <li key={m.y + m.t} className="stage">{m.y && <span className="yr num">{m.y}</span>}<h3>{m.t}</h3>{m.d && <p>{m.d}</p>}</li>)}
      </ol>
    </div></section>
  )
}

/** Careers: the openings register, each with its own Apply, and a row for a CV when nothing listed fits. */
export function Careers({ no, companyId, openings }: { no: number; companyId?: number; openings: Opening[] }) {
  const { COMPANY, SITE } = useContent()
  const cv = `mailto:${COMPANY.email}?subject=${encodeURIComponent('Job application')}`
  return (
    <section className="sec" id="careers" aria-labelledby="careers-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.careers} id="careers-h" />
      <ul className="jobs" aria-label="Openings" style={{ listStyle: 'none' }}>
        {openings.map((o, i) => (
          <li key={o.id} className="job">
            <span className="ref">J-{String(i + 1).padStart(2, '0')}</span>
            <div>
              <h3>{o.title}</h3>
              {(o.location || o.experience) && <p>{[o.location, o.experience && `${o.experience} experience`].filter(Boolean).join(' · ')}</p>}
              {o.description && <p className="desc">{o.description}</p>}
            </div>
            {o.apply_token
              ? <a className="btn btn--solid" href={appUrl(`apply?token=${encodeURIComponent(o.apply_token)}`)} aria-label={`Apply for ${o.title}`}>Apply</a>
              : <a className="btn btn--line" href={cv}>Send your CV</a>}
          </li>
        ))}
        <li className="job">
          <span className="ref">J-{String(openings.length + 1).padStart(2, '0')}</span>
          <div><h3>{openings.length ? 'Not listed?' : 'No openings right now'}</h3><p>Send us your CV and we will keep it for the next opening.</p></div>
          <a className="btn btn--line" href={cv}>Send your CV</a>
        </li>
      </ul>
      {openings.length > 0 && companyId ? <a className="morelink" href={appUrl(`jobs?c=${companyId}`)}>Every opening, with the full details <span className="arrow" aria-hidden="true">→</span></a> : null}
    </div></section>
  )
}

const SOCIAL: [keyof ReturnType<typeof useContent>['COMPANY']['social'], string][] = [['linkedin', 'LinkedIn'], ['facebook', 'Facebook'], ['instagram', 'Instagram'], ['youtube', 'YouTube']]

/** The foot of the page: the drawing's title block, then the copyright and the one Staff login link. */
export function Footer() {
  const { COMPANY, SITE } = useContent()
  const map = `https://www.google.com/maps?q=${encodeURIComponent(COMPANY.address)}`
  const social = SOCIAL.filter(([k]) => COMPANY.social?.[k]?.trim())
  const cells: { key: string; label: string; body: React.ReactNode }[] = []
  if (COMPANY.address) cells.push({ key: 'o', label: 'Office', body: <a className="v" href={map} target="_blank" rel="noopener noreferrer">{COMPANY.address}</a> })
  if (COMPANY.phone.show) cells.push({ key: 'c', label: 'Call', body: <a className="v num" href={`tel:${COMPANY.phone.tel}`}>{COMPANY.phone.show}</a> })
  if (COMPANY.email) cells.push({ key: 'e', label: 'Email', body: <a className="v" href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a> })
  if (SITE.footer.showGroupLink && COMPANY.group.name) cells.push({ key: 'g', label: 'Group company', body: <a className="v" href={COMPANY.group.url} target="_blank" rel="noopener noreferrer">{COMPANY.group.name} ↗</a> })
  if (social.length) cells.push({ key: 's', label: 'Follow', body: <span className="social">{social.map(([k, label]) => <a key={k} className="v" href={COMPANY.social[k]} target="_blank" rel="noopener noreferrer">{label} ↗</a>)}</span> })
  if (SITE.footer.sheet) cells.push({ key: 'sh', label: 'Sheet', body: <span className="v mono">{SITE.footer.sheet}</span> })
  cells.push({ key: 'r', label: 'Rev.', body: <span className="v mono">{YEAR}</span> })
  // Three cells to a row beside the company's box; the last row has no line under it.
  const lastRowFrom = Math.floor((cells.length - 1) / 3) * 3
  const words = COMPANY.name.split(' ')
  return (
    <footer><div className="wrap">
      <div className="titleblock">
        <div className="co" style={{ gridRow: `span ${Math.ceil(cells.length / 3)}` }}><img src={asset('site/img/mark.png')} alt="" width="44" height="44" /><b translate="no">{words[0]}<br />{words.slice(1).join(' ')}</b>{SITE.footer.tagline && <small>{SITE.footer.tagline}</small>}</div>
        {cells.map((c, i) => <div key={c.key} className={i >= lastRowFrom ? 'bot' : undefined}><small>{c.label}</small>{c.body}</div>)}
      </div>
      <div className="fine"><span>© {YEAR} {COMPANY.name}</span><a className="footer__staff" href={appUrl('login')}>Staff login</a></div>
    </div></footer>
  )
}

/** WhatsApp us: phones only, and only once the number is set. */
export function WhatsApp() {
  const { COMPANY } = useContent()
  const n = waNumber(COMPANY.whatsapp || '')
  if (n.length < 10) return null
  return <a className="wa" href={`https://wa.me/${n.length === 10 ? '91' + n : n}`} target="_blank" rel="noopener noreferrer" aria-label="WhatsApp us">WhatsApp us</a>
}
