import { useEffect, useRef } from 'react'
import { Box } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { planTo3d, type Drawing, type Plan3D } from '@/api/drawings'
import { useAction } from '@/lib/mutate'

const WALL_H = 3
const WALL_T = 0.2
const DEFAULT_WIDTH_M = 20

/** Stand the traced plan up as walls on a floor: drag to turn it, scroll to zoom. Disposes everything on close. */
async function mountPlan(canvas: HTMLCanvasElement, plan: Plan3D): Promise<() => void> {
  const T = await import('three')
  const size = plan.width_m || DEFAULT_WIDTH_M
  const scale = size / 100
  const wx = (x: number) => (x - 50) * scale
  const wz = (y: number) => (y - 50) * scale
  const dark = document.documentElement.classList.contains('dark') || window.matchMedia('(prefers-color-scheme: dark)').matches
  const renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  const scene = new T.Scene()
  const cam = new T.PerspectiveCamera(40, 1, 0.1, 1000)
  scene.add(new T.HemisphereLight(0xffffff, 0x555566, 1.1))
  const sun = new T.DirectionalLight(0xffffff, 1.4)
  sun.position.set(20, 40, 15)
  scene.add(sun)

  const wallMat = new T.MeshStandardMaterial({ color: dark ? 0xd4d4d8 : 0x8b8f98, roughness: 0.9 })
  const floorMat = new T.MeshStandardMaterial({ color: dark ? 0x2a2a31 : 0xe4e4e7, roughness: 1 })
  const doorMat = new T.MeshStandardMaterial({ color: 0xb45309 })
  const glassMat = new T.MeshStandardMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.55 })
  const disposables: { dispose(): void }[] = [wallMat, floorMat, doorMat, glassMat]
  const root = new T.Group()
  scene.add(root)

  const floorGeo = new T.BoxGeometry(size * 1.05, 0.15, size * 1.05)
  const floor = new T.Mesh(floorGeo, floorMat)
  floor.position.y = -0.08
  root.add(floor)
  disposables.push(floorGeo)

  for (const w of plan.walls ?? []) {
    const x1 = wx(w.x1), z1 = wz(w.y1), x2 = wx(w.x2), z2 = wz(w.y2)
    const len = Math.hypot(x2 - x1, z2 - z1)
    if (len < 0.05) continue
    const g = new T.BoxGeometry(len, WALL_H, WALL_T)
    const m = new T.Mesh(g, wallMat)
    m.position.set((x1 + x2) / 2, WALL_H / 2, (z1 + z2) / 2)
    m.rotation.y = -Math.atan2(z2 - z1, x2 - x1)
    root.add(m)
    disposables.push(g)
  }
  for (const o of plan.openings ?? []) {
    const win = o.type === 'window'
    const g = new T.BoxGeometry(0.9, win ? 1.1 : 2.1, 0.32)
    const m = new T.Mesh(g, win ? glassMat : doorMat)
    m.position.set(wx(o.x), win ? 1.6 : 1.05, wz(o.y))
    root.add(m)
    disposables.push(g)
  }
  // Room floors, tinted so the rooms read apart.
  ;(plan.rooms ?? []).forEach((r, i) => {
    const g = new T.PlaneGeometry(r.w * scale, r.h * scale)
    const mat = new T.MeshStandardMaterial({ color: new T.Color().setHSL((i * 0.13) % 1, 0.35, dark ? 0.35 : 0.75), side: T.DoubleSide })
    const m = new T.Mesh(g, mat)
    m.rotation.x = -Math.PI / 2
    m.position.set(wx(r.x + r.w / 2), 0.02, wz(r.y + r.h / 2))
    root.add(m)
    disposables.push(g, mat)
  })

  let yaw = 0.6
  let pitch = 0.75
  let dist = size * 1.5
  const place = () => {
    cam.position.set(Math.sin(yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist)
    cam.lookAt(0, WALL_H / 3, 0)
  }
  const resize = () => {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    renderer.setSize(w, h, false)
    cam.aspect = w / Math.max(h, 1)
    cam.updateProjectionMatrix()
  }
  let drag: { x: number; y: number } | null = null
  const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId) }
  const move = (e: PointerEvent) => {
    if (!drag) return
    yaw -= (e.clientX - drag.x) * 0.008
    pitch = Math.max(0.1, Math.min(1.5, pitch + (e.clientY - drag.y) * 0.008))
    drag = { x: e.clientX, y: e.clientY }
  }
  const up = () => { drag = null }
  const wheel = (e: WheelEvent) => { e.preventDefault(); dist = Math.max(size * 0.4, Math.min(size * 4, dist * (1 + e.deltaY * 0.001))) }
  canvas.addEventListener('pointerdown', down)
  canvas.addEventListener('pointermove', move)
  canvas.addEventListener('pointerup', up)
  canvas.addEventListener('wheel', wheel, { passive: false })
  const ro = new ResizeObserver(resize)
  ro.observe(canvas)
  resize()

  let raf = 0
  const frame = () => {
    if (!drag) yaw += 0.002
    place()
    renderer.render(scene, cam)
    raf = requestAnimationFrame(frame)
  }
  frame()
  return () => {
    cancelAnimationFrame(raf)
    ro.disconnect()
    canvas.removeEventListener('pointerdown', down)
    canvas.removeEventListener('pointermove', move)
    canvas.removeEventListener('pointerup', up)
    canvas.removeEventListener('wheel', wheel)
    disposables.forEach((d) => d.dispose())
    renderer.dispose()
  }
}

function Viewer({ plan }: { plan: Plan3D }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    let stop: (() => void) | undefined
    let dead = false
    if (ref.current) mountPlan(ref.current, plan).then((s) => { if (dead) s(); else stop = s }).catch(() => {})
    return () => { dead = true; stop?.() }
  }, [plan])
  return <canvas ref={ref} aria-label="3D view of the plan" className="h-[60vh] w-full cursor-grab rounded-lg border border-border bg-surface active:cursor-grabbing" />
}

/** The current sheet of a drawing, traced into walls and rooms and shown in 3D. A visual aid, never a measurement. */
export function Plan3DModal({ drawing, onClose }: { drawing: Drawing | null; onClose: () => void }) {
  return (
    <Modal open={!!drawing} onOpenChange={(o) => !o && onClose()} title={drawing ? `3D view - ${drawing.number}` : ''} size="lg">
      {drawing && <Plan3DBody key={drawing.id} drawing={drawing} onClose={onClose} />}
    </Modal>
  )
}

function Plan3DBody({ drawing, onClose }: { drawing: Drawing; onClose: () => void }) {
  const run = useAction(() => planTo3d(drawing.id), { success: (r) => (r.available ? 'Plan traced in 3D' : r.message ?? 'Could not make the 3D view') })
  const plan = run.data
  const ok = !!plan?.available && ((plan.walls?.length ?? 0) > 0 || (plan.rooms?.length ?? 0) > 0)
  return (
    <div>
      {!plan && (
        <div className="grid place-items-center gap-3 rounded-lg border border-dashed border-border py-12 text-center">
          <Box className="size-8 text-muted-foreground" />
          <p className="max-w-sm text-[13px] text-muted-foreground">Reads the current sheet ({drawing.current_revision || 'no revision'}) and stands its walls and rooms up in 3D. Works best on a clear floor plan picture or PDF.</p>
          <Button loading={run.isPending} onClick={() => run.mutate()}>{run.isPending ? 'Tracing the plan...' : 'Make the 3D view'}</Button>
          {run.error && <p role="alert" className="text-[13px] text-danger">{run.error.message}</p>}
        </div>
      )}
      {plan && !ok && (
        <div className="grid gap-3 rounded-lg border border-border py-8 text-center">
          <p role="alert" className="text-[13px] text-danger">{plan.message ?? 'Could not make a 3D view from this sheet.'}</p>
          <div><Button variant="outline" size="sm" loading={run.isPending} onClick={() => run.mutate()}>Try again</Button></div>
        </div>
      )}
      {plan && ok && (
        <>
          <Viewer plan={plan} />
          <p className="mt-3 text-[12px] text-muted-foreground">
            {plan.walls?.length ?? 0} walls, {plan.rooms?.length ?? 0} rooms{plan.width_m ? `, about ${plan.width_m} m wide` : ', size estimated'}.
            {plan.low_confidence && ' The sheet was hard to read, so check this against the drawing.'} A visual aid only: do not take quantities from it. Drag to turn, scroll to zoom.
          </p>
        </>
      )}
      <div className="mt-5 flex justify-end border-t border-border pt-4"><Button variant="ghost" onClick={onClose}>Close</Button></div>
    </div>
  )
}
