import * as T from 'three'
import gsap from 'gsap'

// The website was drawn with three.js r128, before colour management. Keep the colours exactly as written.
T.ColorManagement.enabled = false

export const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches
export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))

/** Move numbers on a plain object with GSAP, or jump straight to the end when motion is switched off. */
export function tween<O extends object>(obj: O, to: Partial<Record<keyof O, number>>, dur: number, ease = 'power3.inOut') {
  if (reduceMotion()) return Object.assign(obj, to)
  return gsap.to(obj, { ...to, duration: dur, ease })
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')))
  } catch {
    return false
  }
}

const up = new T.Vector3(0, 1, 0)

/** A thin tube between two points, as geometry. */
export function cyl(a: T.Vector3, b: T.Vector3, r: number) {
  const dir = new T.Vector3().subVectors(b, a)
  const len = dir.length()
  const g = new T.CylinderGeometry(r, r, len, 8, 1, true)
  const m = new T.Matrix4().compose(new T.Vector3().addVectors(a, b).multiplyScalar(0.5), new T.Quaternion().setFromUnitVectors(up, dir.normalize()), new T.Vector3(1, 1, 1))
  return g.applyMatrix4(m)
}

export const joint = (p: T.Vector3, r: number) => new T.SphereGeometry(r * 1.02, 8, 6).translate(p.x, p.y, p.z)

/** Position-only merge, so each system on each floor is a single draw call. */
export function merge(geos: T.BufferGeometry[]) {
  const arrs = geos.map((g) => (g.index ? g.toNonIndexed() : g).attributes.position.array as Float32Array)
  const out = new Float32Array(arrs.reduce((n, a) => n + a.length, 0))
  let o = 0
  arrs.forEach((a) => {
    out.set(a, o)
    o += a.length
  })
  return new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(out, 3))
}

export function boxSegs(arr: number[], x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) {
  const c = [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1], [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]]
  for (const [a, b] of [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]]) arr.push(...c[a], ...c[b])
}

export const geoOf = (arr: number[]) => new T.BufferGeometry().setAttribute('position', new T.Float32BufferAttribute(arr, 3))

/** A polyline measured by length, so pulses travel at an even speed. */
export class Poly extends T.Curve<T.Vector3> {
  pts: T.Vector3[]
  lens: number[] = [0]
  total: number
  constructor(pts: T.Vector3[]) {
    super()
    this.pts = pts
    for (let i = 1; i < pts.length; i++) this.lens.push(this.lens[i - 1] + pts[i].distanceTo(pts[i - 1]))
    this.total = this.lens[this.lens.length - 1] || 1
  }
  getPoint(t: number, target = new T.Vector3()) {
    const d = t * this.total
    let i = 1
    while (i < this.lens.length - 1 && this.lens[i] < d) i++
    const seg = this.lens[i] - this.lens[i - 1] || 1
    return target.copy(this.pts[i - 1]).lerp(this.pts[i], (d - this.lens[i - 1]) / seg)
  }
}

const texture = (draw: (g: CanvasRenderingContext2D) => void) => {
  const c = document.createElement('canvas')
  c.width = c.height = 64
  draw(c.getContext('2d')!)
  return new T.CanvasTexture(c)
}

export const makeGlow = () => texture((g) => {
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32)
  r.addColorStop(0, 'rgba(255,255,255,1)')
  r.addColorStop(0.25, 'rgba(255,255,255,.8)')
  r.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = r
  g.fillRect(0, 0, 64, 64)
})

export const makeDisc = () => texture((g) => {
  g.fillStyle = '#fff'
  g.beginPath()
  g.arc(32, 32, 28, 0, Math.PI * 2)
  g.fill()
})

export function makeRenderer(canvas: HTMLCanvasElement) {
  const r = new T.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' })
  r.outputColorSpace = T.LinearSRGBColorSpace
  r.setPixelRatio(Math.min(devicePixelRatio || 1, 2))
  r.setClearColor(0x000000, 1)
  return r
}

export interface Orbit { theta: number; phi: number; vTheta: number; idle: number; radius: number }

/** Drag to turn: horizontal drags rotate, vertical ones still scroll the page on touch screens. */
export function dragRotate(el: HTMLElement, st: Orbit, opts: { tilt?: [number, number]; range?: number } = {}) {
  let down = false
  let lx = 0
  let ly = 0
  let moved = 0
  const onDown = (e: PointerEvent) => {
    down = true
    moved = 0
    lx = e.clientX
    ly = e.clientY
    el.setPointerCapture?.(e.pointerId)
    el.classList.add('grabbing')
  }
  const onMove = (e: PointerEvent) => {
    if (!down) return
    const dx = e.clientX - lx
    const dy = e.clientY - ly
    lx = e.clientX
    ly = e.clientY
    moved += Math.abs(dx) + Math.abs(dy)
    st.vTheta = -dx * 0.006
    st.theta += st.vTheta
    st.idle = 0
    if (opts.tilt && e.pointerType === 'mouse') st.phi = clamp(st.phi + dy * 0.004, opts.tilt[0], opts.tilt[1])
    if (opts.range) st.theta = clamp(st.theta, -opts.range, opts.range)
  }
  const end = () => {
    down = false
    el.classList.remove('grabbing')
  }
  el.addEventListener('pointerdown', onDown)
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', end)
  el.addEventListener('pointercancel', end)
  el.addEventListener('lostpointercapture', end)
  return {
    moved: () => moved,
    isDown: () => down,
    dispose() {
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', end)
      el.removeEventListener('pointercancel', end)
      el.removeEventListener('lostpointercapture', end)
    },
  }
}

/** Runs `fn` every animation frame until the returned function is called. */
export function loop(fn: (now: number) => void) {
  let id = 0
  const tick = (now: number) => {
    id = requestAnimationFrame(tick)
    fn(now)
  }
  id = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(id)
}
