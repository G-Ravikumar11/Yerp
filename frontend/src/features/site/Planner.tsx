import { useEffect, useState } from 'react'
import { PLAN_TYPES, SITE } from './data/content'
import { goTo } from './Nav'
import { inr } from './lib'
import { briefText, similarProjects, sizeOf, type Plan } from './plan'

/** "Tell us about your project": five questions, and the brief builds beside them. It leaves as an email; nothing is stored. */
export function Planner({ plan, setPlan, toggleScope, toast }: { plan: Plan; setPlan: (f: (p: Plan) => Plan) => void; toggleScope: (id: string) => void; toast: (m: string) => void }) {
  const [city, setCity] = useState(plan.city)
  // The city is taken a moment after typing stops, as the earlier page did.
  useEffect(() => {
    const t = setTimeout(() => setPlan((p) => ({ ...p, city: city.trim() })), 200)
    return () => clearTimeout(t)
  }, [city, setPlan])

  const T = PLAN_TYPES.find((t) => t.id === plan.type)
  const sc = SITE.plan.scopes.filter((s) => plan.scopes.includes(s.id))
  const done = [plan.type, sc.length, plan.city, plan.stage].filter(Boolean).length
  const ready = !!(T && sc.length)
  const sim = similarProjects(plan)
  const mailto = ready ? `mailto:info@yalavarti.com?subject=${encodeURIComponent(`Quote request: ${T!.label}${plan.city ? ', ' + plan.city : ''}`)}&body=${encodeURIComponent(briefText(plan))}` : '#quote'
  const row = (k: string, v: React.ReactNode) => <div><dt>{k}</dt><dd className={v ? undefined : 'empty'}>{v || 'Not set'}</dd></div>

  return (
    <section className="band band--light" id="quote">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Request a Quote</p><h2 className="h2">Tell us about your project</h2></div>
          <p className="lede">Five questions. Your brief builds as you answer, along with comparable projects we&apos;ve delivered.</p>
        </div>
        <div className="plan">
          <form className="plan__form" id="planform" autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <fieldset className="q"><legend><span>01</span>Project type</legend>
              <div className="opts" id="qtype">{SITE.plan.types.map((t) => <label className="opt" key={t.id}><input type="radio" name="type" value={t.id} checked={plan.type === t.id} onChange={() => setPlan((p) => ({ ...p, type: t.id }))} /><span>{t.label}<small>{t.hint}</small></span></label>)}</div>
            </fieldset>
            <fieldset className="q"><legend><span>02</span>Scope</legend>
              <div className="opts" id="qscope">{SITE.plan.scopes.map((s) => <label className="opt" key={s.id}><input type="checkbox" name="scope" value={s.id} checked={plan.scopes.includes(s.id)} onChange={() => toggleScope(s.id)} /><span>{s.label}</span></label>)}</div>
            </fieldset>
            <fieldset className="q"><legend><span>03</span>Built-up area</legend>
              <div className="range">
                <input type="range" id="qsize" name="size" min="0" max="100" value={plan.size} aria-describedby="qsizeout" aria-valuetext={`${inr(sizeOf(plan.size))} sq ft`} style={{ ['--p' as string]: plan.size + '%' }} onChange={(e) => setPlan((p) => ({ ...p, size: Number(e.target.value) }))} />
                <output id="qsizeout" className="num">{inr(sizeOf(plan.size))} sq ft</output>
              </div>
            </fieldset>
            <fieldset className="q"><legend><span>04</span>Site location</legend><label className="sr" htmlFor="qcity">City</label><input className="text" id="qcity" name="city" placeholder="e.g. Hyderabad…" autoComplete="address-level2" value={city} onChange={(e) => setCity(e.target.value)} /></fieldset>
            <fieldset className="q"><legend><span>05</span>Project stage</legend>
              <div className="opts" id="qstage">{SITE.plan.stages.map((s) => <label className="opt" key={s}><input type="radio" name="stage" value={s} checked={plan.stage === s} onChange={() => setPlan((p) => ({ ...p, stage: s }))} /><span>{s}</span></label>)}</div>
            </fieldset>
          </form>
          <aside className="brief" id="brief" aria-live="polite" aria-label="Your brief">
            <div className="brief__head"><p className="eyebrow">Your Brief</p><div className="brief__meter"><span id="briefmeter" style={{ width: (done + 1) * 20 + '%' }} /></div></div>
            <dl className="brief__list" id="brieflist">
              {row('Project', T && <>{T.label}<small>{T.hint}</small></>)}
              {row('Scope', sc.length > 0 && sc.map((s) => <span key={s.id}>{s.label}<small>{s.inc}</small></span>))}
              {row('Area', <><span className="num">{inr(sizeOf(plan.size))}</span> sq ft</>)}
              {row('Site', plan.city)}
              {row('Stage', plan.stage)}
            </dl>
            <div className="brief__similar" id="briefsimilar">
              {T ? (sim.total ? <>{sim.total} comparable {T.label.toLowerCase()} project{sim.total > 1 ? 's' : ''} delivered{sim.local ? ' in ' + plan.city : ''}, including:<ul>{sim.list.map((p, i) => <li key={`${p.n}-${i}`}>{p.n}<span>{p.l.split(',')[0]}</span></li>)}</ul></> : null) : 'Choose a project type to see comparable work.'}
            </div>
            <div className="brief__cta">
              <a className="btn btn--primary" id="briefsend" href={mailto} aria-disabled={!ready} onClick={(e) => { if (!ready) { e.preventDefault(); toast('Choose a project type and at least one scope first'); goTo('#quote') } else toast('Opening your email app…') }}>Email This Brief</a>
              <button className="btn btn--line" id="briefcopy" type="button" onClick={async () => { try { await navigator.clipboard.writeText(briefText(plan)); toast('Brief copied to clipboard') } catch { toast('Copying is blocked here. Use Email This Brief instead.') } }}>Copy</button>
            </div>
            <p className="brief__note">Prefer to talk? <a href="tel:+914040059348">040 4005 9348</a></p>
          </aside>
        </div>
      </div>
    </section>
  )
}
