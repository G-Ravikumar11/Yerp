import { useMemo, useState } from 'react'
import { CREDENTIALS, QUALITY } from './data/credentials'
import { SITE } from './data/content'
import { goTo } from './Nav'
import { asset, inr } from './lib'
import { apiPath, sendEnquiry, type Live, type LiveProject } from './siteApi'

/** The projects ticked "show on website" in our records, with their own photos. Until there is one, a line saying so. */
export function LiveProjects({ live }: { live: Live | null }) {
  const [sector, setSector] = useState('')
  const [city, setCity] = useState('')
  const all = useMemo(() => live?.projects ?? [], [live])
  const sectors = useMemo(() => [...new Set(all.map((p) => p.sector).filter(Boolean))].sort(), [all])
  const cities = useMemo(() => [...new Set(all.map((p) => p.location).filter(Boolean))].sort(), [all])
  const shown = all.filter((p) => (!sector || p.sector === sector) && (!city || p.location === city))
  const chips = (label: string, list: string[], value: string, set: (v: string) => void) => list.length > 1 && (
    <div className="chips" role="group" aria-label={label}>
      <button type="button" className="chip" aria-pressed={!value} onClick={() => set('')}>All</button>
      {list.map((v) => <button key={v} type="button" className="chip" aria-pressed={value === v} onClick={() => set(value === v ? '' : v)}>{v}</button>)}
    </div>
  )
  return (
    <section className="band" id="projects" aria-label="Projects">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Projects</p><h2 className="h2">Recent &amp; ongoing projects</h2></div>
          <p className="lede">{all.length ? 'Where we are building, and our projects with photos from site. Filter by type of work or city.' : 'Where we are building. Photos from site are being added here.'}</p>
        </div>
        <div className="sites" aria-label="Our sites">
          {SITE.sites.map((g) => (
            <div key={g.group} className="sites__group">
              <p className="eyebrow">{g.group} · {g.where}</p>
              <ul>{g.names.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          ))}
        </div>
        {SITE.sitePhotos.length > 0 && (
          <ul className="sites__photos" aria-label="From our sites">
            {SITE.sitePhotos.map((ph) => (
              <li key={ph.img}>
                <figure>
                  <img src={asset(ph.img)} alt={`${ph.site}: ${ph.text}`} loading="lazy" decoding="async" />
                  <figcaption><p className="eyebrow">{ph.site}</p><p>{ph.text}</p></figcaption>
                </figure>
              </li>
            ))}
          </ul>
        )}
        {all.length > 0 && <div className="live__filters">{chips('Type of work', sectors, sector, setSector)}{chips('City', cities, city, setCity)}</div>}
        {all.length > 0 && <ul className="live__grid">{shown.map((p) => <ProjectCard key={p.id} p={p} />)}</ul>}
        {all.length > 0 && !shown.length && <p className="lede">Nothing matches that filter.</p>}
        {!all.length && <a href="#enquire" className="btn btn--ghost" onClick={(e) => goTo('#enquire') && e.preventDefault()}>Ask Us for References</a>}
      </div>
    </section>
  )
}

function ProjectCard({ p }: { p: LiveProject }) {
  const [n, setN] = useState(0)
  const photo = p.photos[n]
  return (
    <li className="live__card">
      <div className="live__img">
        {photo ? <img src={apiPath(photo)} alt={p.name} loading="lazy" decoding="async" /> : <img src={asset('site/img/mark.png')} alt="" className="live__ph" />}
        {p.photos.length > 1 && <button type="button" className="live__more" aria-label={`Next photo of ${p.name}`} onClick={() => setN((n + 1) % p.photos.length)}>{n + 1} / {p.photos.length}</button>}
        <span className={`live__status${p.status === 'Ongoing' ? ' on' : ''}`}>{p.status}</span>
      </div>
      <div className="live__body">
        <p className="eyebrow">{[p.sector, p.location, p.year].filter(Boolean).join(' · ')}</p>
        <h3>{p.name}</h3>
        {p.client && <p className="live__client">For {p.client}</p>}
        {p.scope && <p>{p.scope}</p>}
      </div>
    </li>
  )
}

/** What a tender evaluator looks for. Each line says what it is; documents are sent on request. */
export function Credentials() {
  return (
    <section className="band band--light" id="credentials" aria-label="Credentials">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Credentials</p><h2 className="h2">Registered and accountable</h2></div>
          <p className="lede">The papers a tender asks for. Copies go to evaluators on request.</p>
        </div>
        <dl className="creds">
          {CREDENTIALS.map((c) => <div key={c.label}><dt>{c.label}</dt><dd>{c.value}</dd></div>)}
        </dl>
        <a href="#enquire" className="btn btn--line creds__cta" onClick={(e) => goTo('#enquire') && e.preventDefault()}>Request Documents</a>
      </div>
    </section>
  )
}

/** The policies, and the safe man-hours the ERP counts from attendance and incidents. */
export function QualitySafety({ live }: { live: Live | null }) {
  const hours = live?.numbers.safe_man_hours ?? 0
  return (
    <section className="band" id="safety" aria-label="Quality and safety">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Quality &amp; Safety</p><h2 className="h2">Checked work, safe sites</h2></div>
          {hours > 0 && <p className="safety__hours"><span className="num">{inr(hours)}</span> safe man-hours since the last lost-time injury, counted live from our site records</p>}
        </div>
        <div className="safety__grid">
          {QUALITY.map((q) => (
            <article key={q.title}>
              <h3>{q.title}</h3>
              <p>{q.text}</p>
              {q.link && <a href={asset(q.link.href)} target="_blank" rel="noopener noreferrer" className="safety__link">{q.link.label} ↗</a>}
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

/** An enquiry that reaches the Tender Pipeline. With a brief from the planner, its answers go too. */
export function EnquiryForm({ brief, tone = 'dark', send = 'Send Enquiry', toast }: {
  brief?: { type: string; scopes: string[]; city: string; text: string }; tone?: 'dark' | 'light'; send?: string; toast: (m: string) => void
}) {
  const [f, setF] = useState({ name: '', company: '', phone: '', email: '', city: '', message: '', website: '' })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((x) => ({ ...x, [k]: e.target.value }))
  if (done) return <p className={`enq__done enq--${tone}`} role="status">{done}</p>
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      setDone(await sendEnquiry({
        ...f, city: f.city || brief?.city || '', project_type: brief?.type, scopes: brief?.scopes,
        message: [f.message, brief?.text].filter(Boolean).join('\n\n'),
      }))
    } catch (err) {
      toast(err instanceof Error ? err.message : 'We could not send that. Please call us instead.')
    } finally {
      setBusy(false)
    }
  }
  const field = (k: keyof typeof f, label: string, type = 'text', auto = '') => (
    <label className="enq__f"><span>{label}</span><input className="text" type={type} name={k} autoComplete={auto || undefined} value={f[k]} onChange={set(k)} maxLength={160} /></label>
  )
  return (
    <form className={`enq enq--${tone}`} onSubmit={submit} aria-label="Enquiry">
      {field('name', 'Your name', 'text', 'name')}
      {field('company', 'Company', 'text', 'organization')}
      {field('phone', 'Phone', 'tel', 'tel')}
      {field('email', 'Email', 'email', 'email')}
      {!brief && field('city', 'Site city', 'text', 'address-level2')}
      <label className="enq__f enq__wide"><span>{brief ? 'Anything else' : 'Your enquiry'}</span><textarea className="text" name="message" rows={3} value={f.message} onChange={set('message')} maxLength={3000} /></label>
      {/* Left empty by people. A form-filling robot fills it in, and its enquiry is quietly dropped. */}
      <label className="sr" aria-hidden="true">Website<input tabIndex={-1} autoComplete="off" name="website" value={f.website} onChange={set('website')} /></label>
      <button className="btn btn--primary enq__wide" type="submit" disabled={busy}>{busy ? 'Sending…' : send}</button>
    </form>
  )
}
