import * as T from 'three'
import { boxSegs, clamp, cyl, dragRotate, geoOf, joint, loop, makeDisc, makeGlow, makeRenderer, merge, Poly, reduceMotion, tween, type Orbit } from './kit'

export type SystemId = 'all' | 'elec' | 'fire' | 'phe'
type Sys = 'elec' | 'fire' | 'phe'

export interface BuildingApi {
  setSystem(s: SystemId): void
  setExplode(on: boolean): void
  dispose(): void
}

interface GroupData {
  kind: 'floor' | 'roof' | 'base' | 'site'
  index: number
  pipes: Record<Sys, T.BufferGeometry[]>
  lines: Record<'struct' | 'faint' | Sys, number[]>
  fills: [string, number, number, number, number, number, number][]
  heads: { fire: number[] }
  shown?: number
}
type Grp = T.Group & { userData: GroupData }
interface Flow { g: Grp; sys: Sys; c: Poly; speed: number; ph: number }

/**
 * A high-rise drawn in lines, with the electrical, fire and plumbing systems traced through it. It turns when dragged,
 * can be pulled apart floor by floor, and shows one system at a time.
 */
export function mountBuilding(view: HTMLElement, canvas: HTMLCanvasElement, labelsEl: HTMLElement): BuildingApi {
  const reduce = reduceMotion()
  const disc = makeDisc()
  const glow = makeGlow()
  const renderer = makeRenderer(canvas)
  const scene = new T.Scene()
  scene.fog = new T.Fog(0x000000, 110, 230)
  const cam = new T.PerspectiveCamera(30, 1, 0.5, 500)
  const V = (x: number, y: number, z: number) => new T.Vector3(x, y, z)

  const N = 12
  const H = 3.2
  const W2 = 9
  const D2 = 6
  const TOP = N * H
  const B = -4.6
  const SYS: Record<Sys, number> = { elec: 0x4da3ff, fire: 0xff4b3a, phe: 0x2fd3c4 }
  const KEYS = Object.keys(SYS) as Sys[]
  const mat = {} as Record<Sys, T.MeshBasicMaterial>
  const lineMat = {} as Record<Sys, T.LineBasicMaterial>
  const fillMat = {} as Record<Sys, T.MeshBasicMaterial>
  const headMat = {} as Record<Sys, T.PointsMaterial>
  KEYS.forEach((k) => {
    const c = SYS[k]
    mat[k] = new T.MeshBasicMaterial({ color: c, transparent: true })
    lineMat[k] = new T.LineBasicMaterial({ color: c, transparent: true, opacity: 0.5 })
    fillMat[k] = new T.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.14, depthWrite: false })
    headMat[k] = new T.PointsMaterial({ color: c, size: 0.32, map: disc, transparent: true, alphaTest: 0.4 })
  })
  const structMat = new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22 })
  const faintMat = new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.07 })
  const slabMat = new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.035, depthWrite: false, side: T.DoubleSide })

  const groups: Grp[] = []
  const flows: Flow[] = []
  const floors: Grp[] = []
  const G = (kind: GroupData['kind'], index: number) => {
    const g = new T.Group() as Grp
    g.userData = { kind, index, pipes: { elec: [], fire: [], phe: [] }, lines: { struct: [], faint: [], elec: [], fire: [], phe: [] }, fills: [], heads: { fire: [] } }
    scene.add(g)
    groups.push(g)
    return g
  }
  const pipe = (g: Grp, sys: Sys, pts: number[][], r: number, speed?: number, sync?: boolean) => {
    const v = pts.map((p) => V(p[0], p[1], p[2]))
    const list = g.userData.pipes[sys]
    for (let i = 1; i < v.length; i++) list.push(cyl(v[i - 1], v[i], r))
    for (let i = 1; i < v.length - 1; i++) list.push(joint(v[i], r))
    if (!speed) return
    const c = new Poly(v)
    const n = Math.max(1, Math.round(c.total / 7))
    // Riser segments share one phase so the pulses read as one continuous train up the shaft.
    for (let k = 0; k < n; k++) flows.push({ g, sys, c, speed, ph: sync ? 0 : k / n + Math.random() * 0.3 })
  }
  const box = (g: Grp, set: 'struct' | 'faint' | Sys, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, fill?: string) => {
    boxSegs(g.userData.lines[set], x0, y0, z0, x1, y1, z1)
    if (fill) g.userData.fills.push([fill, x0, y0, z0, x1, y1, z1])
  }
  const finalize = (g: Grp) => {
    const u = g.userData
    KEYS.forEach((k) => {
      if (u.pipes[k].length) g.add(new T.Mesh(merge(u.pipes[k]), mat[k]))
      if (u.lines[k].length) g.add(new T.LineSegments(geoOf(u.lines[k]), lineMat[k]))
    })
    if (u.heads.fire.length) g.add(new T.Points(geoOf(u.heads.fire), headMat.fire))
    if (u.lines.struct.length) g.add(new T.LineSegments(geoOf(u.lines.struct), structMat))
    if (u.lines.faint.length) g.add(new T.LineSegments(geoOf(u.lines.faint), faintMat))
    u.fills.forEach(([k, x0, y0, z0, x1, y1, z1]) => {
      const m = new T.Mesh(new T.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), k === 'slab' ? slabMat : fillMat[k as Sys])
      m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
      g.add(m)
    })
  }

  // Typical floors
  for (let i = 0; i < N; i++) {
    const g = G('floor', i)
    const y0 = i * H
    const y1 = y0 + H
    const hc = y1 - 0.45
    const hs = hc - 0.45
    const hw = y0 + 0.35
    const f = g.userData.lines.faint
    floors.push(g)
    box(g, 'struct', -W2, y0, -D2, W2, y0 + 0.18, D2, 'slab')
    box(g, 'struct', -1.5, y0 + 0.18, -1.5, 1.5, y1, 1.5)
    for (let x = -W2; x <= W2 + 0.01; x += 1.5) f.push(x, y0, -D2, x, y1, -D2, x, y0, D2, x, y1, D2)
    for (let z = -D2 + 1.5; z < D2 - 0.01; z += 1.5) f.push(-W2, y0, z, -W2, y1, z, W2, y0, z, W2, y1, z)
    // electrical: busduct segment, trays at ceiling, floor DB
    pipe(g, 'elec', [[1, y0, 1], [1, y1, 1]], 0.22, 7, true)
    pipe(g, 'elec', [[1, hc, 1], [1, hc, -4.6], [7.8, hc, -4.6], [7.8, hc, 4.6], [2.4, hc, 4.6]], 0.09, 6)
    pipe(g, 'elec', [[1, hc, -4.6], [-7.8, hc, -4.6], [-7.8, hc, 1.6]], 0.09, 6)
    box(g, 'elec', 1.7, y0 + 0.4, 0.3, 2.3, y0 + 1.9, 1.5, 'elec')
    // fire: wet riser segment, mains, sprinkler branches and heads
    pipe(g, 'fire', [[-1, y0, -1], [-1, y1, -1]], 0.2, 6, true)
    pipe(g, 'fire', [[-1, hs, -1], [-1, hs, -3], [-8.2, hs, -3]], 0.1, 5)
    pipe(g, 'fire', [[-1, hs, -3], [8.2, hs, -3]], 0.1, 5)
    for (const x of [-7, -5, -3, 3, 5, 7]) {
      g.userData.lines.fire.push(x, hs, -3, x, hs, 5.2)
      for (let z = -1.3; z <= 5.2; z += 1.6) g.userData.heads.fire.push(x, hs - 0.12, z)
    }
    // plumbing: supply riser down, branch to wet areas, drainage stack down
    pipe(g, 'phe', [[-1, y1, 1], [-1, y0, 1]], 0.17, 5, true)
    pipe(g, 'phe', [[-1, hw, 1], [-1, hw, 4.8], [-6.2, hw, 4.8]], 0.08, 4)
    pipe(g, 'phe', [[-6.9, y1, 5.3], [-6.9, y0, 5.3]], 0.22, 3.5, true)
    box(g, 'phe', -6.3, y0 + 0.18, 3.9, -4.5, y0 + 0.9, 5.6, 'phe')
    finalize(g)
  }

  // Roof: slab, parapet, lift room, overhead tank
  const roof = G('roof', N)
  box(roof, 'struct', -W2, TOP, -D2, W2, TOP + 0.18, D2, 'slab')
  box(roof, 'faint', -W2, TOP + 0.18, -D2, W2, TOP + 1.1, D2)
  box(roof, 'struct', -1.5, TOP + 0.18, -1.5, 1.5, TOP + 3, 1.5)
  box(roof, 'phe', -5.4, TOP + 0.18, 1.6, -2.2, TOP + 2.6, 4.8, 'phe')
  pipe(roof, 'phe', [[-2.2, TOP + 0.6, 3], [-1, TOP + 0.6, 3], [-1, TOP + 0.6, 1], [-1, TOP, 1]], 0.17, 4)
  finalize(roof)

  // Basement: LT panel room, fire tank and pumps, STP
  const base = G('base', -1)
  box(base, 'struct', -W2, B, -D2, W2, B + 0.18, D2, 'slab')
  box(base, 'faint', -W2, B, -D2, W2, 0, D2)
  for (let k = 0; k < 4; k++) box(base, 'elec', 3.4 + k * 1.05, B + 0.18, 3.6, 4.3 + k * 1.05, B + 2.3, 4.4, 'elec')
  pipe(base, 'elec', [[12.2, 0.1, 4.6], [12.2, -2.6, 4.6], [7.6, -2.6, 4.6], [7.6, -2.6, 4]], 0.16, 6)
  pipe(base, 'elec', [[3.4, -2.6, 4], [1, -2.6, 4], [1, -2.6, 1], [1, 0, 1]], 0.22, 7)
  box(base, 'fire', -8.6, B + 0.18, -5.6, -4.2, -1.2, -1.6, 'fire')
  for (const z of [-4.8, -3.8, -2.8]) pipe(base, 'fire', [[-3.8, B + 0.8, z], [-2.5, B + 0.8, z]], 0.34)
  pipe(base, 'fire', [[-4.2, B + 0.8, -3.8], [-3.8, B + 0.8, -3.8]], 0.14)
  pipe(base, 'fire', [[-2.5, B + 0.8, -3.8], [-1, B + 0.8, -3.8], [-1, B + 0.8, -1], [-1, 0, -1]], 0.2, 6)
  pipe(base, 'fire', [[-2.5, B + 0.8, -4.8], [-2.5, B + 0.8, -8.5], [-2.5, -0.3, -8.5]], 0.14, 4)
  box(base, 'phe', -8.6, B + 0.18, 2, -5.8, B + 2.4, 5.6, 'phe')
  pipe(base, 'phe', [[-6.9, 0, 5.3], [-6.9, -2, 5.3], [-7.2, -2, 4.6]], 0.22, 3.5)
  finalize(base)

  // Site: ground grid, transformer yard, HT line, hydrant ring main
  const site = G('site', 0)
  const gl = site.userData.lines.faint
  const P = 21
  for (let x = -30; x <= 36; x += 3) (Math.abs(x) < W2 ? [[-26, -D2], [D2, 26]] : [[-26, 26]]).forEach(([a, b]) => gl.push(x, 0, a, x, 0, b))
  for (let z = -24; z <= 24; z += 3) (Math.abs(z) < D2 ? [[-32, -W2], [W2, 38]] : [[-32, 38]]).forEach(([a, b]) => gl.push(a, 0, z, b, 0, z))
  box(site, 'elec', 11, 0, 3.2, 13.4, 2.4, 5.6, 'elec')
  box(site, 'faint', 9.8, 0, 1.8, 15, 2.2, 7)
  site.userData.lines.struct.push(P, 0, 4.4, P, 9, 4.4, P - 1.6, 8.2, 4.4, P + 1.6, 8.2, 4.4, P - 1, 0, 4.4, P, 5, 4.4, P + 1, 0, 4.4, P, 5, 4.4)
  pipe(site, 'elec', [[P + 9, 9.6, 4.4], [P, 8.2, 4.4], [17, 5.8, 4.4], [13.4, 2.4, 4.4]], 0.07, 8)
  pipe(site, 'fire', [[-12, -0.3, -8.5], [13, -0.3, -8.5], [13, -0.3, 8.5], [-12, -0.3, 8.5], [-12, -0.3, -8.5]], 0.14, 4)
  for (const [x, z] of [[-12, -8.5], [0.5, -8.5], [13, -8.5], [13, 0], [13, 8.5], [0.5, 8.5], [-12, 8.5], [-12, 0]]) pipe(site, 'fire', [[x, -0.3, z], [x, 1.1, z]], 0.22)
  finalize(site)

  // Flow pulses: one glowing point cloud per system
  const pulses = {} as Record<Sys, { list: Flow[]; geo: T.BufferGeometry; pm: T.PointsMaterial; pts: T.Points }>
  KEYS.forEach((k) => {
    const list = flows.filter((f) => f.sys === k)
    const geo = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(list.length * 3), 3))
    const pm = new T.PointsMaterial({ color: SYS[k], size: 1.5, map: glow, transparent: true, depthWrite: false, blending: T.AdditiveBlending })
    const pts = new T.Points(geo, pm)
    pts.frustumCulled = false
    scene.add(pts)
    pulses[k] = { list, geo, pm, pts }
  })

  // Labels anchored to parts of the model
  const L = (sys: Sys, g: Grp, p: number[], t: string, main?: boolean) => ({ sys, g, p: V(p[0], p[1], p[2]), t, main: !!main })
  const labels = [
    L('elec', site, [P, 9.4, 4.4], 'HT Incomer'),
    L('elec', site, [12.2, 2.9, 4.4], 'Transformer'),
    L('elec', base, [5.5, -2, 4], 'LT Panels'),
    L('elec', floors[6], [1, 6 * H + 1.6, 1], 'Rising Busduct', true),
    L('elec', floors[10], [7.8, 11 * H - 0.45, 0], 'Cable Trays & Floor DBs'),
    L('fire', base, [-6.4, -1, -3.6], 'Fire Water Tank'),
    L('fire', base, [-3.1, B + 1.4, -3.8], 'Fire Pumps'),
    L('fire', floors[9], [-1, 9 * H + 1.6, -1], 'Wet Riser', true),
    L('fire', floors[11], [-7, 12 * H - 0.9, 2], 'Sprinkler Network'),
    L('fire', site, [13, 1.2, -8.5], 'Hydrant Ring Main'),
    L('phe', roof, [-3.8, TOP + 2.8, 3.2], 'Overhead Tank', true),
    L('phe', floors[3], [-1, 3 * H + 1.6, 1], 'Water Supply Riser'),
    L('phe', floors[2], [-6.9, 2 * H + 1.6, 5.3], 'Drainage Stack'),
    L('phe', base, [-7.2, -2, 3.8], 'Sewage Treatment'),
  ]
  const labEls = labels.map((l) => {
    const d = document.createElement('div')
    d.className = `lab lab--${l.sys}`
    d.innerHTML = `<i></i><span>${l.t}</span>`
    labelsEl.appendChild(d)
    return d
  })

  const st: Orbit & { explode: number; build: number; sys: SystemId; alpha: Record<Sys, number> } = {
    theta: 0.7, phi: 0.34, vTheta: 0, idle: 0, radius: 95, explode: 0, build: reduce ? 1 : 0, sys: 'all', alpha: { elec: 1, fire: 1, phe: 1 },
  }
  const drag = dragRotate(canvas, st, { tilt: [0.06, 0.9] })
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') { st.theta += 0.25; st.idle = 0; e.preventDefault() }
    if (e.key === 'ArrowRight') { st.theta -= 0.25; st.idle = 0; e.preventDefault() }
  }
  view.addEventListener('keydown', onKey)

  let vw = 1
  let vh = 1
  const resize = () => {
    const w = view.clientWidth
    const h = view.clientHeight
    if (!w || !h) return
    vw = w
    vh = h
    renderer.setSize(w, h, false)
    cam.aspect = w / h
    cam.updateProjectionMatrix()
    const a = w / h
    st.radius = a < 0.75 ? 165 : a < 1.15 ? 128 : 98
  }
  const ro = new ResizeObserver(resize)
  ro.observe(view)
  resize()

  let visible = false
  let started = false
  let time = 0
  let last = performance.now()
  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting
    if (visible && !started) {
      started = true
      if (!reduce) tween(st, { build: 1 }, 3.2, 'none')
    }
  }, { threshold: 0.2 })
  io.observe(view)

  const tmp = V(0, 0, 0)
  const wp = V(0, 0, 0)
  const target = V(3, 15, 0)
  const stop = loop((now) => {
    if (!visible) { last = now; return }
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now
    if (!reduce) time += dt
    if (!drag.isDown()) {
      st.idle += dt
      st.theta += st.vTheta
      st.vTheta *= 0.92
      if (!reduce && st.idle > 2.5) st.theta += dt * 0.08
    }
    // floors drop into place one after another, and spread apart in exploded view
    groups.forEach((g) => {
      const u = g.userData
      const lift = u.kind === 'floor' ? (u.index + 1) * 1.8 : u.kind === 'roof' ? (N + 1) * 1.8 : u.kind === 'base' ? -2.8 : 0
      const order = u.kind === 'floor' ? u.index + 1 : u.kind === 'roof' ? N + 1 : 0
      const l = clamp((st.build - order * 0.05) / 0.3, 0, 1)
      const e = 1 - Math.pow(1 - l, 3)
      g.visible = l > 0
      u.shown = l
      g.position.y = st.explode * lift + (1 - e) * 18
    })
    // dim the systems that are not selected
    KEYS.forEach((k) => {
      const want = st.sys === 'all' || st.sys === k ? 1 : 0.07
      const a = (st.alpha[k] += (want - st.alpha[k]) * Math.min(1, dt * 7))
      mat[k].opacity = a
      lineMat[k].opacity = 0.5 * a
      fillMat[k].opacity = 0.14 * a
      headMat[k].opacity = a
      const p = pulses[k]
      p.pm.opacity = a
      p.pts.visible = a > 0.12
      const arr = p.geo.attributes.position.array as Float32Array
      p.list.forEach((f, i) => {
        if (!f.g.visible) { arr[i * 3 + 1] = -999; return }
        f.c.getPoint((((f.ph + (time * f.speed) / f.c.total) % 1) + 1) % 1, tmp)
        arr[i * 3] = tmp.x
        arr[i * 3 + 1] = tmp.y + f.g.position.y
        arr[i * 3 + 2] = tmp.z
      })
      p.geo.attributes.position.needsUpdate = true
    })
    const r = st.radius * (1 + st.explode * 0.55)
    target.y = 16 + st.explode * 14
    cam.position.set(target.x + r * Math.cos(st.phi) * Math.sin(st.theta), target.y + r * Math.sin(st.phi), r * Math.cos(st.phi) * Math.cos(st.theta))
    cam.lookAt(target)
    renderer.render(scene, cam)
    // labels follow their anchors on screen
    labels.forEach((l, i) => {
      const el = labEls[i]
      const show = l.g.visible && (l.g.userData.shown ?? 0) > 0.9 && (st.sys === 'all' ? l.main : l.sys === st.sys)
      wp.copy(l.p)
      wp.y += l.g.position.y
      wp.project(cam)
      const on = !!(show && wp.z < 1 && Math.abs(wp.x) < 1.05 && Math.abs(wp.y) < 1.05)
      el.classList.toggle('on', on)
      if (on) el.style.transform = `translate3d(${(((wp.x + 1) / 2) * vw).toFixed(1)}px,${(((1 - wp.y) / 2) * vh).toFixed(1)}px,0)`
    })
  })
  view.classList.add('ready')

  return {
    setSystem(s) {
      st.sys = s
      view.dataset.sys = s
    },
    setExplode(on) {
      tween(st, { explode: on ? 1 : 0 }, 1.3)
    },
    dispose() {
      stop()
      io.disconnect()
      ro.disconnect()
      drag.dispose()
      view.removeEventListener('keydown', onKey)
      labEls.forEach((e) => e.remove())
      scene.traverse((o) => {
        const m = o as T.Mesh
        m.geometry?.dispose?.()
      })
      renderer.dispose()
      view.classList.remove('ready')
    },
  }
}
