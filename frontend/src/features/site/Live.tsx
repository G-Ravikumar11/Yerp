import { useMemo, useState } from 'react'
import { credentialShown, type RegisterRow, type Sheet } from './data/content'
import { DTitle, stateName, waNumber } from './Parts'
import { imgSrc, inr, sitePath } from './lib'
import { useContent } from './siteContent'
import { apiPath, sendEnquiry, type Live, type LiveProject } from './siteApi'

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

/** The register: the sites listed in Settings -> Website, and the live projects ticked "show on website" that are not one of
 *  them already. A live project that is one of them lends it its progress. */
export function registerRows(sites: RegisterRow[], live: Live | null) {
  const projects = live?.projects ?? []
  const used = new Set<number>()
  const rows = sites.filter((r) => r.site.trim()).map((r) => {
    const p = projects.find((x) => !used.has(x.id) && (norm(x.name) === norm(r.site) || norm(x.name).includes(norm(r.site))))
    if (p) used.add(p.id)
    return { ...r, progress: p?.progress ?? null, project: p ?? null }
  })
  for (const p of projects) {
    if (used.has(p.id)) continue
    rows.push({ site: p.name, client: p.client, town: p.location, state: '', work: p.sector, status: p.status, progress: p.progress ?? null, project: p })
  }
  return rows
}

/** Drawing sheets: the site photographs from Settings -> Website, then each live project with photographs of its own. */
export function sheetsFrom(photos: Sheet[], live: Live | null): (Sheet & { photos: string[] })[] {
  const own = photos.filter((s) => s.img).map((s) => ({ ...s, photos: [imgSrc(s.img)] }))
  const fromProjects = (live?.projects ?? []).filter((p) => p.photos.length).map((p, i) => ({
    img: '', site: p.name, ref: `P-${String(i + 1).padStart(2, '0')}`, block: '', stage: p.status, shown: p.scope, photos: p.photos.map((u) => apiPath(u)),
  }))
  return [...own, ...fromProjects]
}

/** A drawing sheet. `all`: every photograph at once (the projects page); otherwise one, with a button to the next. */
export function SheetCard({ s, all = false }: { s: Sheet & { photos: string[] }; all?: boolean }) {
  const [n, setN] = useState(0)
  const cells: [string, string][] = ([['Block', s.block], ['Stage', s.stage], ['Shown', s.shown]] as [string, string][]).filter(([, v]) => v.trim())
  return (
    <article className="psheet">
      {all && s.photos.length > 1
        ? <div className="gallery">{s.photos.map((u) => <img key={u} src={u} alt={s.site} loading="lazy" decoding="async" />)}</div>
        : (
          <div className="more">
            <img src={s.photos[n]} alt={[s.site, s.shown].filter(Boolean).join(': ')} loading="lazy" decoding="async" width="1200" height="750" />
            {s.photos.length > 1 && <button type="button" aria-label={`Next photograph of ${s.site}`} onClick={() => setN((n + 1) % s.photos.length)}>{n + 1} / {s.photos.length}</button>}
          </div>
        )}
      <div className="tb">
        <div className="wide"><small>Sheet{s.ref ? ` ${s.ref}` : ''} · from site</small><h3>{s.site}</h3></div>
        {cells.map(([k, v]) => <div key={k}><small>{k}</small><span className="v">{v}</span></div>)}
      </div>
    </article>
  )
}

/** Projects: the register of every site in hand, filtered by state, then the large drawing sheets. */
export function Projects({ no, live }: { no: number; live: Live | null }) {
  const { SITE } = useContent()
  const rows = useMemo(() => registerRows(SITE.sites, live), [SITE.sites, live])
  const [state, setState] = useState('')
  const states = useMemo(() => [...new Set(rows.map((r) => r.state.trim().toUpperCase()).filter(Boolean))], [rows])
  const shown = rows.filter((r) => !state || r.state.trim().toUpperCase() === state)
  const progress = SITE.options.showProgress && rows.some((r) => r.progress != null)
  const sheets = sheetsFrom(SITE.sitePhotos, live)
  const [first, ...rest] = sheets
  return (
    <section className="sec sec--tint" id="projects" aria-labelledby="projects-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.projects} id="projects-h" />
      {rows.length > 0 && (
        <>
          {states.length > 1 && (
            <div className="filters" role="group" aria-label="Filter by state">
              <button className="chip" type="button" aria-pressed={!state} onClick={() => setState('')}>All · {rows.length}</button>
              {states.map((s) => <button key={s} className="chip" type="button" aria-pressed={state === s} onClick={() => setState(state === s ? '' : s)}>{stateName(s)} · {rows.filter((r) => r.state.trim().toUpperCase() === s).length}</button>)}
            </div>
          )}
          <div className="reg"><table>
            <caption className="sr">Projects register</caption>
            <thead><tr><th scope="col">Ref</th><th scope="col">Site</th><th scope="col">Client / programme</th><th scope="col">Town</th><th scope="col">Work</th><th scope="col">Status</th>{progress && <th scope="col">Progress</th>}</tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.site + r.town}>
                  <td className="ref">S-{String(rows.indexOf(r) + 1).padStart(2, '0')}</td>
                  <td className="site">{r.site}</td>
                  <td className={r.client ? undefined : 'empty'}>{r.client || '-'}</td>
                  <td>{[r.town, r.state].filter(Boolean).join(', ') || '-'}</td>
                  <td className={r.work ? undefined : 'empty'}>{r.work || '-'}</td>
                  <td>{r.status && <span className={`st${/complet/i.test(r.status) ? ' st--done' : ''}`}>{r.status}</span>}</td>
                  {progress && <td>{r.progress != null && <span className="bar" aria-label={`${r.progress}% done`}><i style={{ ['--p' as string]: `${r.progress}%` }} />{r.progress}%</span>}</td>}
                </tr>
              ))}
            </tbody>
          </table></div>
        </>
      )}
      {first && (
        <div className={`sheets${rest.length ? '' : ' sheets--one'}`}>
          <SheetCard s={first} />
          {rest.length > 0 && <div className="side">{rest.slice(0, 2).map((s) => <SheetCard key={s.site + s.ref} s={s} />)}</div>}
        </div>
      )}
      {sheets.length > 0 && <a className="morelink" href={sitePath('projects')}>Every project, with photos <span className="arrow" aria-hidden="true">→</span></a>}
    </div></section>
  )
}

/** Quality and safety: the three policies, the credentials register (only items with a real value) and the safe man-hours,
 *  shown once past the level the company set. */
export function Quality({ no, live }: { no: number; live: Live | null }) {
  const { SITE } = useContent()
  const policies = SITE.safety.filter((q) => q.title.trim())
  const creds = SITE.credentials.filter(credentialShown)
  const hours = live?.numbers.safe_man_hours ?? 0
  const from = SITE.options.safeHoursFrom ?? 0
  const showHours = hours > 0 && hours >= from
  const ask = <a className="btn btn--line" href="#quote">Request documents</a>
  return (
    <section className="sec" id="quality" aria-labelledby="quality-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.quality} id="quality-h" />
      {policies.length > 0 && (
        <div className="qs" style={{ ['--n' as string]: Math.min(policies.length, 3) }}>
          {policies.map((q) => (
            <article key={q.title}>
              {q.code && <small>{q.code}</small>}
              <h3>{q.title}</h3>
              <p>{q.text}</p>
              {q.link?.href && <a href={imgSrc(q.link.href)} target="_blank" rel="noopener noreferrer">{q.link.label || 'Read it'} ↗</a>}
            </article>
          ))}
        </div>
      )}
      {(creds.length > 0 || showHours) && (
        <div className={`creds${creds.length && showHours ? '' : ' creds--one'}`}>
          {creds.length > 0 && (
            <div>
              <dl aria-label="Credentials">{creds.map((c) => <div key={c.label}><dt>{c.label}</dt><dd>{c.value}</dd></div>)}</dl>
              {!showHours && <div style={{ marginTop: '1.2rem' }}>{ask}</div>}
            </div>
          )}
          {showHours && (
            <div className="hours">
              <small>Safe man-hours since the last lost-time injury</small>
              <b className="num">{inr(hours)}</b>
              <p>Counted live from site attendance and incident records.</p>
              {ask}
            </div>
          )}
        </div>
      )}
    </div></section>
  )
}

/** Start a project: one enquiry form - the kind of work, who, where, how big and when - beside what happens next and the
 *  ways to reach us directly. It arrives as a new lead in the Tender Pipeline, with the kind of work. */
export function Quote({ no, type, setType, toast }: { no: number; type: string; setType: (t: string) => void; toast: (m: string) => void }) {
  const { COMPANY, SITE } = useContent()
  const types = SITE.plan.types
  const [f, setF] = useState({ name: '', phone: '', email: '', city: '', area: '', start: '', message: '', website: '' })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }))
  const label = types.find((t) => t.id === type)?.label ?? ''
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      setDone(await sendEnquiry({
        name: f.name, company: '', phone: f.phone, email: f.email, city: f.city, website: f.website,
        project_type: label || undefined, scopes: [],
        message: [f.message.trim(), f.area.trim() && `Plot or built-up area: ${f.area.trim()}`, f.start && `Expected start: ${f.start}`].filter(Boolean).join('\n'),
      }))
    } catch (err) {
      toast(err instanceof Error ? err.message : 'We could not send that. Please call us instead.')
    } finally {
      setBusy(false)
    }
  }
  const wa = waNumber(COMPANY.whatsapp || '')
  const map = `https://www.google.com/maps?q=${encodeURIComponent(COMPANY.address)}`
  const next = SITE.enquiry.next.filter((s) => s.t.trim())
  return (
    <section className="sec sec--tint" id="quote" aria-labelledby="quote-h"><div className="wrap">
      <DTitle no={no} h={SITE.headings.quote} id="quote-h" />
      <div className="quote">
        {done ? <p className="enq__done" role="status"><small>Enquiry sent</small>{done}</p> : (
          <form className="enq" onSubmit={submit} aria-label="Enquiry" id="enquire">
            <fieldset className="fs">
              <legend>Type of work</legend>
              <div className="types" role="group" aria-label="Type of work">
                {types.map((t) => <button key={t.id} type="button" className="chip" aria-pressed={type === t.id} title={t.hint} onClick={() => setType(type === t.id ? '' : t.id)}>{t.label}</button>)}
              </div>
            </fieldset>
            <div className="f f--l"><label htmlFor="q-name">Your name</label><input id="q-name" name="name" autoComplete="name" maxLength={120} required value={f.name} onChange={set('name')} /></div>
            <div className="f"><label htmlFor="q-phone">Phone</label><input id="q-phone" name="phone" type="tel" autoComplete="tel" maxLength={40} value={f.phone} onChange={set('phone')} /></div>
            <div className="f f--l"><label htmlFor="q-email">Email</label><input id="q-email" name="email" type="email" autoComplete="email" maxLength={160} value={f.email} onChange={set('email')} /></div>
            <div className="f"><label htmlFor="q-city">Site location</label><input id="q-city" name="city" autoComplete="address-level2" placeholder="Area and city" maxLength={80} value={f.city} onChange={set('city')} /></div>
            <div className="f f--l"><label htmlFor="q-area">Plot or built-up area</label><input id="q-area" name="area" placeholder="e.g. 2,400 sq ft" maxLength={60} value={f.area} onChange={set('area')} /></div>
            <div className="f"><label htmlFor="q-start">Expected start</label>
              <select id="q-start" name="start" value={f.start} onChange={set('start')}><option value="">Choose</option>{SITE.plan.starts.map((s) => <option key={s}>{s}</option>)}</select>
            </div>
            <div className="f f--full"><label htmlFor="q-msg">Anything else</label><textarea id="q-msg" name="message" rows={3} maxLength={3000} value={f.message} onChange={set('message')} /></div>
            {/* Left empty by people. A form-filling robot fills it in, and its enquiry is quietly dropped. */}
            <label className="sr" aria-hidden="true">Website<input tabIndex={-1} autoComplete="off" name="website" value={f.website} onChange={set('website')} /></label>
            <div className="send">
              <small>{SITE.enquiry.note}</small>
              <button className="btn btn--solid" type="submit" disabled={busy}>{busy ? 'Sending…' : <>Send enquiry <span className="arrow" aria-hidden="true">→</span></>}</button>
            </div>
          </form>
        )}
        <div className="next">
          {next.length > 0 && <ol aria-label="What happens next">{next.map((s) => <li key={s.t}><b>{s.t}</b>{s.d}</li>)}</ol>}
          <div className="direct" id="contact">
            {COMPANY.phone.show && <a href={`tel:${COMPANY.phone.tel}`}><small>Call</small><span className="num">{COMPANY.phone.show}</span></a>}
            {wa.length >= 10 && <a href={`https://wa.me/${wa.length === 10 ? '91' + wa : wa}`} target="_blank" rel="noopener noreferrer"><small>WhatsApp</small><span className="num">{COMPANY.whatsapp}</span></a>}
            {COMPANY.email && <a href={`mailto:${COMPANY.email}`}><small>Email</small><span>{COMPANY.email}</span></a>}
            {COMPANY.address && <a href={map} target="_blank" rel="noopener noreferrer"><small>Office</small><span>{COMPANY.address} ↗</span></a>}
          </div>
        </div>
      </div>
    </div></section>
  )
}

export type { LiveProject }
