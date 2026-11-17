import { COMPANY, SITE } from './data/content'
import { goTo } from './Nav'
import { EnquiryForm } from './Live'
import { areaText, briefText, typeLabel, type Plan } from './plan'

/** "Tell us about your project": four questions, and the brief builds beside them. Sent with a name and a number, it
 *  arrives as a new lead in the Tender Pipeline; it can still be emailed or copied instead. */
export function Planner({ plan, setPlan, toast }: { plan: Plan; setPlan: (f: (p: Plan) => Plan) => void; toast: (m: string) => void }) {
  const T = SITE.plan.types.find((t) => t.id === plan.type)
  const area = areaText(plan)
  const done = [plan.type, plan.city.trim(), area, plan.start].filter(Boolean).length
  const ready = !!T
  const mailto = ready ? `mailto:${COMPANY.email}?subject=${encodeURIComponent(`Enquiry: ${T!.label}${plan.city.trim() ? ', ' + plan.city.trim() : ''}`)}&body=${encodeURIComponent(briefText(plan))}` : '#quote'
  const row = (k: string, v: React.ReactNode) => <div><dt>{k}</dt><dd className={v ? undefined : 'empty'}>{v || 'Not set'}</dd></div>
  const set = (k: keyof Plan) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { const v = e.target.value; setPlan((p) => ({ ...p, [k]: v })) }

  return (
    <section className="band band--light" id="quote">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Start a Project</p><h2 className="h2">Tell us about your project</h2></div>
          <p className="lede">Four questions. Your brief builds as you answer, and comes straight to our team.</p>
        </div>
        <div className="plan">
          <form className="plan__form" id="planform" autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <fieldset className="q"><legend><span>01</span>Type of work</legend>
              <div className="opts" id="qtype">{SITE.plan.types.map((t) => <label className="opt" key={t.id}><input type="radio" name="type" value={t.id} checked={plan.type === t.id} onChange={() => setPlan((p) => ({ ...p, type: t.id }))} /><span>{t.label}<small>{t.hint}</small></span></label>)}</div>
            </fieldset>
            <fieldset className="q"><legend><span>02</span>Location</legend>
              <label className="sr" htmlFor="qcity">Site location</label>
              <input className="text" id="qcity" name="city" placeholder="Area and city, e.g. Kokapet, Hyderabad…" autoComplete="address-level2" maxLength={80} value={plan.city} onChange={set('city')} />
            </fieldset>
            <fieldset className="q"><legend><span>03</span>Plot or built-up area</legend>
              <div className="area">
                <label className="sr" htmlFor="qarea">Area</label>
                <input className="text num" id="qarea" name="area" inputMode="decimal" placeholder="e.g. 2,400" maxLength={12} value={plan.area} onChange={(e) => { const v = e.target.value.replace(/[^\d.,]/g, ''); setPlan((p) => ({ ...p, area: v })) }} />
                <label className="sr" htmlFor="qunit">Unit</label>
                <select className="text" id="qunit" name="unit" value={plan.unit} onChange={set('unit')}>{SITE.plan.units.map((u) => <option key={u}>{u}</option>)}</select>
              </div>
            </fieldset>
            <fieldset className="q"><legend><span>04</span>Expected start</legend>
              <div className="opts" id="qstart">{SITE.plan.starts.map((s) => <label className="opt" key={s}><input type="radio" name="start" value={s} checked={plan.start === s} onChange={() => setPlan((p) => ({ ...p, start: s }))} /><span>{s}</span></label>)}</div>
            </fieldset>
          </form>
          <aside className="brief" id="brief" aria-live="polite" aria-label="Your brief">
            <div className="brief__head"><p className="eyebrow">Your Brief</p><div className="brief__meter"><span id="briefmeter" style={{ width: done * 25 + '%' }} /></div></div>
            <dl className="brief__list" id="brieflist">
              {row('Work', T && <>{T.label}<small>{T.hint}</small></>)}
              {row('Location', plan.city.trim())}
              {row('Area', area)}
              {row('Start', plan.start)}
            </dl>
            {ready
              ? <div className="brief__send"><EnquiryForm tone="light" send="Send This Brief" toast={toast} brief={{ type: typeLabel(plan.type), scopes: [], city: plan.city.trim(), text: briefText(plan) }} /></div>
              : <p className="brief__note">Choose the type of work, then send the brief with your name and number.</p>}
            <div className="brief__cta">
              <a className="btn btn--line" id="briefsend" href={mailto} aria-disabled={!ready} onClick={(e) => { if (!ready) { e.preventDefault(); toast('Choose the type of work first'); goTo('#quote') } else toast('Opening your email app…') }}>Email Instead</a>
              <button className="btn btn--line" id="briefcopy" type="button" onClick={async () => { try { await navigator.clipboard.writeText(briefText(plan)); toast('Brief copied to clipboard') } catch { toast('Copying is blocked here. Use Email Instead.') } }}>Copy</button>
            </div>
            <p className="brief__note">Prefer to talk? <a href={`tel:${COMPANY.phone.tel}`}>{COMPANY.phone.show}</a></p>
          </aside>
        </div>
      </div>
    </section>
  )
}
