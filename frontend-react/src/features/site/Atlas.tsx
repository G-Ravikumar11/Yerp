import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { PLACES, SITE } from './data/content'
import { PROJECTS } from './data/projects'
import { reduceMotion, useNear } from './lib'
import type { MapApi } from './scenes/map'

const CATS = ['All', 'Commercial', 'Residential', 'Industrial', 'IT & SEZ', 'Hospitality']
const IDLE = 'Select a city to filter projects'
const PAGE = 10

// Words in the project list that mean each place.
const TERMS: Record<string, string[]> = { Hyderabad: ['hyderabad', 'jadcherla', 'sangareddy', 'beeramguda', 'nalgonda', 'hitech', 'jubilee'], Chennai: ['chennai'], Bengaluru: ['bangalore', 'bengaluru'], Bhubaneswar: ['odisha'], Noida: ['noida'], Nagpur: ['nagpur'], Jammu: ['jammu'], Lucknow: ['lucknow'], 'Naya Raipur': ['raipur'], Bhilai: ['bhilai'], Mumbai: ['mumbai'], Pune: ['pune'], Jharsuguda: ['jharsuguda'], Koraput: ['koraput'], Visakhapatnam: ['vizag'], 'Amaravati / Guntur': ['amaravati', 'guntur', 'mangalagiri'], Nellore: ['nellore'], Raichur: ['raichur'], Tiruchi: ['tiruchi'] }
const termsOf = (n: string) => TERMS[n] || [n.toLowerCase()]
const matchPlace = (p: { n: string; l: string }, terms: string[]) => terms.some((t) => `${p.n} ${p.l}`.toLowerCase().includes(t))

// The outline of India, drawn once as dots on a 600 x 680 sheet.
const MIN_LON = 67.5, MAX_LON = 97.8, MIN_LAT = 7.5, MAX_LAT = 37.3, W = 600, H = 680
const proj = ([lon, lat]: [number, number]): [number, number] => [((lon - MIN_LON) / (MAX_LON - MIN_LON)) * W, ((MAX_LAT - lat) / (MAX_LAT - MIN_LAT)) * H]

function outline() {
  const poly = (SITE.india as number[][]).map((p) => proj([p[0], p[1]]))
  const inside = (x: number, y: number) => {
    let c = false
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i]
      const [xj, yj] = poly[j]
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c
    }
    return c
  }
  const dots: [number, number][] = []
  for (let y = 4; y < H; y += 10) for (let x = 4; x < W; x += 10) if (inside(x, y)) dots.push([x, y])
  return dots
}

/** The map of India and the project index beside it: pick a city, a sector or search, and the list follows. */
export function Atlas() {
  const places = PLACES
  const dots = useMemo(outline, [])
  const counts = useMemo(() => places.map((pl) => PROJECTS.filter((p) => matchPlace(p, termsOf(pl.n))).length), [places])

  const [cat, setCat] = useState('All')
  const [q, setQ] = useState('')
  const [place, setPlace] = useState<{ terms: string[]; name: string } | null>(null)
  const [limit, setLimit] = useState(PAGE)
  const [sel, setSel] = useState<number | null>(null)
  const [tip, setTip] = useState<React.ReactNode>(IDLE)
  const [is3d, setIs3d] = useState(false)
  const [nearRef, near] = useNear<HTMLDivElement>()

  const all = useMemo(() => PROJECTS.filter((p) => (cat === 'All' || p.s === cat) && (!q || `${p.n} ${p.l} ${p.c} ${p.w}`.toLowerCase().includes(q)) && (!place || matchPlace(p, place.terms))), [cat, q, place])
  const shown = all.slice(0, limit)

  const reset = () => { setSel(null); setTip(IDLE) }
  const clearPlace = () => { setPlace(null); reset() }
  const pick = (i: number) => {
    const pl = places[i]
    const n = counts[i]
    setSel(i)
    setTip(<><b>{pl.n}</b> — {pl.note}. {n ? `${n} project${n > 1 ? 's' : ''}.` : 'Regional office.'} <button type="button" id="mapclear" onClick={clearPlace}>Show All</button></>)
    if (n) { setPlace({ terms: termsOf(pl.n), name: pl.n }); setQ(''); setCat('All'); setLimit(PAGE) }
  }

  // The newest rows fade in, whether the list was just filtered or just grown.
  const listRef = useRef<HTMLOListElement>(null)
  const before = useRef(0)
  useEffect(() => {
    const kids = listRef.current ? [...listRef.current.children].slice(before.current > shown.length ? 0 : before.current) : []
    before.current = shown.length
    if (!reduceMotion() && kids.length) gsap.fromTo(kids, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.45, stagger: 0.03, ease: 'power3.out' })
  }, [shown.length, cat, q, place])

  // The 3D map, once it is about to be seen. The box is shown first and the scene made after, because a hidden box
  // has no size for the scene to measure or to watch.
  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const labelsRef = useRef<HTMLDivElement>(null)
  const api = useRef<MapApi | null>(null)
  const latest = useRef({ pick, clearPlace })
  latest.current = { pick, clearPlace }
  useEffect(() => {
    if (!near) return
    let dead = false
    void import('./scenes/kit').then(({ hasWebGL }) => { if (!dead && hasWebGL()) setIs3d(true) })
    return () => { dead = true }
  }, [near])
  useEffect(() => {
    if (!is3d || !boxRef.current || !canvasRef.current || !labelsRef.current) return
    let dead = false
    void import('./scenes/map').then(({ mountMap }) => {
      if (dead) return
      api.current = mountMap(boxRef.current!, canvasRef.current!, labelsRef.current!, { places, dots, proj, counts }, {
        pick: (i) => latest.current.pick(i),
        clear: () => latest.current.clearPlace(),
        hint: (i) => setTip(<><b>{places[i].n}</b> — {places[i].note}. Press Enter to filter.</>),
      })
    }).catch((e) => { console.warn('3D view unavailable:', e?.message); setIs3d(false) })
    return () => { dead = true; api.current?.dispose(); api.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [is3d])
  useEffect(() => api.current?.setSelected(sel), [sel, is3d])

  const hq = proj(places[0].p)
  return (
    <section className="band" id="projects">
      <div className="wrap">
        <div className="sechead sechead--split">
          <div><p className="eyebrow">Project Index</p><h2 className="h2"><span className="num" id="ptotal">{PROJECTS.length}</span> Projects Across India</h2></div>
          <p className="lede">Select a city on the map, a sector, or search by client.</p>
        </div>
        <div className="atlas">
          <div className={`atlas__map${is3d ? ' is3d' : ''}`} ref={nearRef}>
            <svg id="mapsvg" viewBox="0 0 600 680" role="img" aria-label="Map of India with Yalavarti offices and project sites">
              <g>{dots.map(([x, y]) => <circle key={`${x}-${y}`} className="dot" cx={x} cy={y} r="1.7" />)}</g>
              <g>{places.map((pl, i) => {
                if (!i || pl.k !== 'br') return null
                const [x, y] = proj(pl.p)
                return <path key={pl.n} className="arc" d={`M${hq[0]} ${hq[1]} Q${(x + hq[0]) / 2} ${(y + hq[1]) / 2 - Math.hypot(x - hq[0], y - hq[1]) * 0.3} ${x} ${y}`} />
              })}</g>
              <g>{places.map((pl, i) => {
                const [x, y] = proj(pl.p)
                const c = pl.k === 'hq' ? 'var(--blue-h)' : pl.k === 'br' ? '#fff' : '#8a8a90'
                const r = pl.k === 'hq' ? 6 : pl.k === 'br' ? 4 : 2.6
                const left = pl.n === 'Bengaluru'
                return (
                  <g key={pl.n} className={`pin${sel === i ? ' sel' : ''}`} tabIndex={0} role="button" aria-label={`${pl.n}: ${pl.note}`} onClick={() => pick(i)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(i) } }}>
                    <circle className="ring" cx={x} cy={y} r="12" /><circle className="core" cx={x} cy={y} r={r} fill={c} /><circle cx={x} cy={y} r="15" fill="transparent" />
                    {pl.k !== 'site' && <text x={left ? x - 10 : x + 10} y={y + 4} textAnchor={left ? 'end' : undefined}>{pl.n}</text>}
                  </g>
                )
              })}</g>
            </svg>
            <div className="map3d" id="map3dwrap" ref={boxRef} tabIndex={0} aria-label="3D map of India. Column height shows projects per city. Use the arrow keys to move between cities and Enter to filter the list.">
              <canvas id="map3d" ref={canvasRef} aria-hidden="true" />
              <div className="map3d__labels" id="maplabels" ref={labelsRef} aria-hidden="true" />
            </div>
            <p className="atlas__tip" id="maptip" aria-live="polite">{tip}</p>
          </div>
          <div>
            <div className="filters">
              <div className="chips" id="pchips">
                {CATS.map((c) => <button key={c} className="chip" type="button" aria-pressed={cat === c} onClick={() => { setCat(c); setLimit(PAGE) }}>{c}<small>{c === 'All' ? PROJECTS.length : PROJECTS.filter((p) => p.s === c).length}</small></button>)}
              </div>
              <label className="search"><span className="sr">Search projects</span>
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
                <input id="psearch" type="search" name="q" placeholder="Search project, city or client…" autoComplete="off" spellCheck={false} defaultValue="" onChange={(e) => { const v = e.target.value.trim().toLowerCase(); setQ(v); setPlace(null); setLimit(PAGE); reset() }} />
              </label>
            </div>
            <p className="presult" id="presult" aria-live="polite">Showing {shown.length} of {all.length}{place ? ' in ' + place.name : ''}{cat !== 'All' ? ' · ' + cat : ''}</p>
            <ol className="plist" id="plist" ref={listRef}>
              {shown.length ? shown.map((p, i) => (
                <li className="prow" key={`${p.n}-${p.l}-${p.y}-${i}`}><h4>{p.n}</h4><span className="prow__y">{p.o ? 'Recent' : p.y || ''}</span><p><span className="prow__s">{p.s}</span>{[p.l, p.w, p.c].filter(Boolean).join(' · ')}</p></li>
              )) : <li className="pempty">No projects match. Try a city such as Chennai, or a client such as L&amp;T.</li>}
            </ol>
            <button className="btn btn--ghost pmore" id="pmore" type="button" hidden={all.length <= limit} onClick={() => setLimit((l) => l + PAGE)}>Show More</button>
          </div>
        </div>
      </div>
    </section>
  )
}
