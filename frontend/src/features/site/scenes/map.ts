import * as T from 'three'
import type { Place } from '../data/content'
import { dragRotate, loop, makeDisc, makeGlow, makeRenderer, reduceMotion, tween, type Orbit, geoOf } from './kit'

export interface MapData {
  places: Place[]
  /** The dots that draw the outline of India, in the 600 x 680 drawing's own units. */
  dots: [number, number][]
  proj: (p: [number, number]) => [number, number]
  /** How many projects each place has. */
  counts: number[]
}

export interface MapEvents {
  pick(i: number): void
  clear(): void
  /** Called with the place the keyboard is on, or -1 when it leaves. */
  hint(i: number): void
}

export interface MapApi {
  setSelected(i: number | null): void
  dispose(): void
}

const COL = { hq: 0x2b95ff, br: 0xf2f2f2, site: 0x8e8e96 }

/** India as dots, with a column of light for every place: taller where there are more projects. */
export function mountMap(box: HTMLElement, canvas: HTMLCanvasElement, labelsEl: HTMLElement, data: MapData, ev: MapEvents): MapApi {
  const reduce = reduceMotion()
  const disc = makeDisc()
  const glow = makeGlow()
  const renderer = makeRenderer(canvas)
  const scene = new T.Scene()
  const cam = new T.PerspectiveCamera(30, 1, 1, 600)
  const to3 = ([px, py]: [number, number]): [number, number] => [(px - 300) / 10, (py - 340) / 10]

  const dp: number[] = []
  data.dots.forEach((d) => {
    const [x, z] = to3(d)
    dp.push(x, 0, z)
  })
  scene.add(new T.Points(geoOf(dp), new T.PointsMaterial({ color: 0x5a5a64, size: 0.5, map: disc, transparent: true, alphaTest: 0.4 })))

  // vertical fade: bright at the base, dim at the top
  const gradCanvas = document.createElement('canvas')
  gradCanvas.width = 4
  gradCanvas.height = 128
  const gc = gradCanvas.getContext('2d')!
  const lg = gc.createLinearGradient(0, 0, 0, 128)
  lg.addColorStop(0, '#2a2a2e')
  lg.addColorStop(1, '#ffffff')
  gc.fillStyle = lg
  gc.fillRect(0, 0, 4, 128)
  const grad = new T.CanvasTexture(gradCanvas)

  const hits: T.Mesh[] = []
  const cols = data.places.map((pl, i) => {
    const [x, z] = to3(data.proj(pl.p))
    const n = data.counts[i]
    const h = (pl.k === 'hq' ? 2 : pl.k === 'br' ? 1.2 : 0.8) + Math.sqrt(n) * 2.3
    const r = pl.k === 'hq' ? 0.6 : pl.k === 'br' ? 0.45 : 0.32
    const m = new T.Mesh(new T.CylinderGeometry(r, r, h, 24).translate(0, h / 2, 0), new T.MeshBasicMaterial({ color: COL[pl.k], map: grad }))
    m.position.set(x, 0, z)
    scene.add(m)
    const ring = new T.Mesh(new T.RingGeometry(r * 1.8, r * 2.4, 40), new T.MeshBasicMaterial({ color: COL[pl.k], transparent: true, opacity: 0.45, side: T.DoubleSide, depthWrite: false }))
    ring.rotation.x = -Math.PI / 2
    ring.position.set(x, 0.03, z)
    scene.add(ring)
    const hit = new T.Mesh(new T.CylinderGeometry(1.4, 1.4, h + 2, 8).translate(0, (h + 2) / 2, 0), new T.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false }))
    hit.position.set(x, 0, z)
    hit.userData.i = i
    scene.add(hit)
    hits.push(hit)
    return { m, ring, h, x, z, pl, n, grow: reduce ? 1 : 0 }
  })

  // arcs from Hyderabad to each branch, with pulses running out along them
  const hq = cols[0]
  const arcs: T.QuadraticBezierCurve3[] = []
  cols.forEach((c) => {
    if (c.pl.k !== 'br') return
    const d = Math.hypot(c.x - hq.x, c.z - hq.z)
    const curve = new T.QuadraticBezierCurve3(new T.Vector3(hq.x, 0.1, hq.z), new T.Vector3((c.x + hq.x) / 2, d * 0.38, (c.z + hq.z) / 2), new T.Vector3(c.x, 0.1, c.z))
    scene.add(new T.Line(new T.BufferGeometry().setFromPoints(curve.getPoints(60)), new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22 })))
    arcs.push(curve)
  })
  const pg = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(arcs.length * 2 * 3), 3))
  const pp = new T.Points(pg, new T.PointsMaterial({ color: 0x9fd0ff, size: 1.6, map: glow, transparent: true, depthWrite: false, blending: T.AdditiveBlending }))
  pp.frustumCulled = false
  scene.add(pp)

  // name tags for the office cities, and one floating tag for the hovered column
  const tags = cols.map((c) => {
    const d = document.createElement('div')
    d.className = `mlab${c.pl.k === 'site' ? ' mlab--site' : ''}${c.pl.n === 'Bengaluru' || c.pl.n === 'Hyderabad' ? ' mlab--left' : c.pl.n === 'Chennai' ? ' mlab--right' : ''}`
    d.innerHTML = `<b>${c.pl.n}</b>${c.n ? `<span>${c.n} project${c.n > 1 ? 's' : ''}</span>` : ''}`
    labelsEl.appendChild(d)
    return d
  })

  const st: Orbit = { theta: 0, phi: 1.12, vTheta: 0, idle: 0, radius: 112 }
  const drag = dragRotate(canvas, st, { range: 0.75 })
  let hover = -1
  let sel: number | null = null
  let focusIdx = -1

  const ray = new T.Raycaster()
  const ndc = new T.Vector2()
  const pickAt = (e: MouseEvent) => {
    const r = canvas.getBoundingClientRect()
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    ray.setFromCamera(ndc, cam)
    const hit = ray.intersectObjects(hits)[0]
    return hit ? (hit.object.userData.i as number) : -1
  }
  const onMove = (e: PointerEvent) => {
    if (drag.isDown()) return
    hover = pickAt(e)
    canvas.style.cursor = hover >= 0 ? 'pointer' : ''
  }
  const onLeave = () => { hover = -1 }
  const onClick = (e: MouseEvent) => {
    if (drag.moved() > 6) return
    const i = pickAt(e)
    if (i >= 0) ev.pick(i)
  }
  const onKey = (e: KeyboardEvent) => {
    const n = cols.length
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { focusIdx = (focusIdx + 1) % n; e.preventDefault() }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { focusIdx = (focusIdx - 1 + n) % n; e.preventDefault() }
    else if ((e.key === 'Enter' || e.key === ' ') && focusIdx >= 0) { ev.pick(focusIdx); e.preventDefault(); return }
    else if (e.key === 'Escape') { ev.clear(); return }
    else return
    ev.hint(focusIdx)
  }
  const onBlur = () => { focusIdx = -1 }
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerleave', onLeave)
  canvas.addEventListener('click', onClick)
  box.addEventListener('keydown', onKey)
  box.addEventListener('blur', onBlur)

  let bw = 1
  let bh = 1
  const resize = () => {
    const w = box.clientWidth
    const h = box.clientHeight
    if (!w || !h) return
    bw = w
    bh = h
    renderer.setSize(w, h, false)
    cam.aspect = w / h
    cam.updateProjectionMatrix()
    st.radius = w / h < 0.8 ? 128 : 112
  }
  const ro = new ResizeObserver(resize)
  ro.observe(box)
  resize()

  let visible = false
  let started = false
  let time = 0
  let last = performance.now()
  const timers: number[] = []
  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting
    if (visible && !started) {
      started = true
      cols.forEach((c, i) => {
        if (!reduce) timers.push(window.setTimeout(() => tween(c, { grow: 1 }, 1.4, 'expo.out'), 120 + i * 60))
      })
    }
  }, { threshold: 0.2 })
  io.observe(box)

  const tv = new T.Vector3()
  const tp = new T.Vector3()
  const target = new T.Vector3(0, 0, 1.5)
  const stop = loop((now) => {
    if (!visible) { last = now; return }
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now
    if (!reduce) time += dt
    if (!drag.isDown()) {
      st.idle += dt
      st.theta += st.vTheta
      st.vTheta *= 0.9
      if (!reduce && st.idle > 2) st.theta += (Math.sin(time * 0.25) * 0.22 - st.theta) * dt * 0.6
    }
    cam.position.set(target.x + st.radius * Math.cos(st.phi) * Math.sin(st.theta), st.radius * Math.sin(st.phi), target.z + st.radius * Math.cos(st.phi) * Math.cos(st.theta))
    cam.lookAt(target)
    const active = hover >= 0 ? hover : focusIdx
    cols.forEach((c, i) => {
      const on = i === active || i === sel
      c.m.scale.y = Math.max(0.001, c.grow)
      ;(c.m.material as T.MeshBasicMaterial).color.setHex(on ? 0xffffff : COL[c.pl.k])
      const pulse = c.pl.k === 'site' ? 1 : 1 + ((time * 0.6 + i * 0.17) % 1) * 0.8
      c.ring.scale.setScalar(on ? 1.6 : pulse)
      ;(c.ring.material as T.MeshBasicMaterial).opacity = on ? 0.9 : c.pl.k === 'site' ? 0.3 : 0.5 * (1 - ((time * 0.6 + i * 0.17) % 1) * 0.8)
    })
    const arr = pg.attributes.position.array as Float32Array
    arcs.forEach((a, i) => [0, 0.5].forEach((o, k) => {
      a.getPoint((time * 0.35 + o + i * 0.13) % 1, tp)
      arr.set([tp.x, tp.y, tp.z], (i * 2 + k) * 3)
    }))
    pg.attributes.position.needsUpdate = true
    renderer.render(scene, cam)
    cols.forEach((c, i) => {
      const el = tags[i]
      const show = c.pl.k !== 'site' || i === active || i === sel
      tv.set(c.x, c.h * c.grow + 1.2, c.z).project(cam)
      const on = !!(show && c.grow > 0.6 && tv.z < 1)
      el.classList.toggle('on', on)
      el.classList.toggle('hot', i === active || i === sel)
      if (on) el.style.transform = `translate3d(${(((tv.x + 1) / 2) * bw).toFixed(1)}px,${(((1 - tv.y) / 2) * bh).toFixed(1)}px,0)`
    })
  })

  return {
    setSelected(i) { sel = i },
    dispose() {
      stop()
      io.disconnect()
      ro.disconnect()
      timers.forEach(clearTimeout)
      drag.dispose()
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerleave', onLeave)
      canvas.removeEventListener('click', onClick)
      box.removeEventListener('keydown', onKey)
      box.removeEventListener('blur', onBlur)
      tags.forEach((t) => t.remove())
      scene.traverse((o) => (o as T.Mesh).geometry?.dispose?.())
      renderer.dispose()
    },
  }
}
