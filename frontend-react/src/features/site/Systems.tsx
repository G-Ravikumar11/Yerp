import { useEffect, useRef, useState } from 'react'
import { asset, useNear } from './lib'
import type { BuildingApi, SystemId } from './scenes/building'

const INFO: Record<SystemId, [string, string, string?]> = {
  all: ['All Systems', 'A typical high-rise with every system we install. Select one to trace it from source to outlet.'],
  elec: ['Electrical', 'From the utility HT incomer through the transformer and LT panels, up the rising busduct to distribution boards and cable trays on every floor.', 'electrical'],
  fire: ['Fire Protection', 'Fire water storage and pumps feed a wet riser, a sprinkler network on every floor and a hydrant ring main around the site.', 'fire'],
  phe: ['Plumbing', 'An overhead tank feeds supply risers to every floor, while drainage stacks carry waste down to the sewage treatment plant.', 'phe'],
}

/** The 3D building: drag to turn it, pick a system to follow it from source to outlet, or pull the floors apart. */
export function Systems({ scopes, toggle }: { scopes: string[]; toggle: (id: string) => void }) {
  const [sys, setSys] = useState<SystemId>('all')
  const [explode, setExplode] = useState(false)
  const [noGl, setNoGl] = useState(false)
  const [nearRef, near] = useNear<HTMLElement>()
  const viewRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const labelsRef = useRef<HTMLDivElement>(null)
  const api = useRef<BuildingApi | null>(null)

  useEffect(() => {
    if (!near || !viewRef.current || !canvasRef.current || !labelsRef.current) return
    let dead = false
    void (async () => {
      const [{ hasWebGL }, { mountBuilding }] = await Promise.all([import('./scenes/kit'), import('./scenes/building')])
      if (dead) return
      if (!hasWebGL()) return setNoGl(true)
      api.current = mountBuilding(viewRef.current!, canvasRef.current!, labelsRef.current!)
      api.current.setSystem(sys)
      api.current.setExplode(explode)
    })().catch((e) => { console.warn('3D view unavailable:', e?.message); setNoGl(true) })
    return () => { dead = true; api.current?.dispose(); api.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [near])
  useEffect(() => api.current?.setSystem(sys), [sys])
  useEffect(() => api.current?.setExplode(explode), [explode])

  const [name, text, scope] = INFO[sys]
  const added = scope ? scopes.includes(scope) : false
  return (
    <section className="band systems" id="systems" aria-label="Building systems in 3D" ref={nearRef}>
      <div className="wrap sechead sechead--split">
        <div><p className="eyebrow">Inside a Yalavarti Building</p><h2 className="h2">Every system, traced in 3D</h2></div>
        <p className="lede">Drag to turn the tower. Pick a system to follow it from source to outlet, or open the floors to look inside.</p>
      </div>
      <div className="wrap stage">
        <div className="stage__bar">
          <div className="seg" id="sysbtns" role="group" aria-label="Show system">
            <button type="button" aria-pressed={sys === 'all'} onClick={() => setSys('all')}>All Systems</button>
            <button type="button" aria-pressed={sys === 'elec'} onClick={() => setSys('elec')}><i className="sw sw--elec" aria-hidden="true" />Electrical</button>
            <button type="button" aria-pressed={sys === 'fire'} onClick={() => setSys('fire')}><i className="sw sw--fire" aria-hidden="true" />Fire Protection</button>
            <button type="button" aria-pressed={sys === 'phe'} onClick={() => setSys('phe')}><i className="sw sw--phe" aria-hidden="true" />Plumbing</button>
          </div>
          <button type="button" className="seg__toggle" id="explode" aria-pressed={explode} onClick={() => setExplode((e) => !e)}>Exploded View</button>
        </div>
        <div className={`stage__view${noGl ? ' nogl' : ''}`} id="stageview" ref={viewRef} data-sys={sys} tabIndex={0} aria-label="3D model of a high-rise building. Use the left and right arrow keys to turn it.">
          <canvas id="bldg" ref={canvasRef} aria-hidden="true" />
          <div className="stage__labels" id="bldglabels" ref={labelsRef} aria-hidden="true" />
          <div className="stage__fallback"><img src={asset('site/img/gallery/g119.jpg')} alt="Fire protection risers installed by Yalavarti" loading="lazy" width="2122" height="1415" /><p>The 3D view needs WebGL, which this browser has turned off.</p></div>
          <p className="stage__hint eyebrow" aria-hidden="true">Drag to Rotate</p>
        </div>
        <div className="stage__info" aria-live="polite">
          <div><p className="eyebrow" id="sysk">{name}</p><p id="sysd">{text}</p></div>
          <button type="button" className="btn btn--ghost btn--sm" id="sysadd" hidden={!scope} onClick={() => scope && toggle(scope)}>{added ? `${name} Added to Quote ✓` : `Add ${name} to Quote +`}</button>
        </div>
      </div>
    </section>
  )
}
