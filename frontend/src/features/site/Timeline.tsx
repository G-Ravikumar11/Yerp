import { useEffect, useRef } from 'react'
import { SITE } from './data/content'
import { asset, reduceMotion } from './lib'

/** The milestones: a pinned stage where scrolling down slides the cards sideways, each turning as it passes the middle. */
export function Timeline() {
  const sec = useRef<HTMLElement>(null)
  const pin = useRef<HTMLDivElement>(null)
  const track = useRef<HTMLDivElement>(null)
  const bar = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const s = sec.current!
    const p = pin.current!
    const t = track.current!
    const b = bar.current!
    const cards = [...t.querySelectorAll<HTMLElement>('.tl')]
    const reduce = reduceMotion()
    const wide = matchMedia('(min-width: 901px)')
    let sticky = false
    let dist = 0
    let centres: number[] = []
    let raf = 0

    const update = () => {
      raf = 0
      let x: number
      let prog: number
      if (sticky) {
        prog = Math.max(0, Math.min(1, (scrollY - s.offsetTop) / Math.max(1, dist)))
        x = prog * dist
        t.style.transform = `translate3d(${-x.toFixed(1)}px,0,0)`
      } else {
        x = p.scrollLeft
        prog = x / Math.max(1, p.scrollWidth - p.clientWidth)
      }
      b.style.transform = `scaleX(${prog})`
      if (reduce) return
      // cards turn in 3D as they pass the centre of the screen
      const mid = innerWidth / 2
      cards.forEach((c, i) => {
        const d = Math.max(-1.6, Math.min(1.6, (centres[i] - x - mid) / mid))
        c.style.transform = `perspective(1400px) rotateY(${(-d * 24).toFixed(2)}deg) translateZ(${(-Math.abs(d) * 140).toFixed(1)}px)`
        c.style.opacity = (1 - Math.min(0.55, Math.abs(d) * 0.35)).toFixed(3)
      })
    }
    // Native position: sticky rather than a JS pin, so nothing snaps when the section starts or ends.
    const measure = () => {
      sticky = wide.matches && !reduce
      s.classList.toggle('timeline--sticky', sticky)
      t.style.transform = ''
      centres = cards.map((c) => c.offsetLeft - t.offsetLeft + c.offsetWidth / 2)
      dist = Math.max(0, t.scrollWidth - innerWidth)
      s.style.height = sticky ? `${Math.round(innerHeight + dist)}px` : ''
      update()
    }
    const req = () => { if (!raf) raf = requestAnimationFrame(update) }
    addEventListener('scroll', req, { passive: true })
    p.addEventListener('scroll', req, { passive: true })
    addEventListener('resize', measure)
    wide.addEventListener?.('change', measure)
    addEventListener('load', measure)
    void document.fonts?.ready.then(measure)
    measure()
    return () => {
      removeEventListener('scroll', req)
      p.removeEventListener('scroll', req)
      removeEventListener('resize', measure)
      wide.removeEventListener?.('change', measure)
      removeEventListener('load', measure)
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <section className="timeline" id="company" aria-label="Milestones" ref={sec}>
      <div className="timeline__pin" ref={pin}>
        <div className="wrap sechead"><p className="eyebrow">Since 1998</p><h2 className="h2">Milestones</h2></div>
        <div className="timeline__track" id="tltrack" ref={track}>
          {SITE.timeline.map((m) => (
            <article className="tl" key={m.y}>
              <p className="tl__y">{m.y}</p>
              <div className="tl__img"><img src={asset(m.img)} alt="" loading="lazy" width="340" height="227" /></div>
              <h3>{m.t}</h3>
              <p>{m.d}</p>
            </article>
          ))}
        </div>
        <div className="wrap"><div className="timeline__bar"><span id="tlbar" ref={bar} /></div></div>
      </div>
    </section>
  )
}
