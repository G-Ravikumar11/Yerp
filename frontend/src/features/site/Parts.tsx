import type { Heading } from './data/content'

/** A section's heading, drawn as a drawing title: its number and one-word code in a circle split by a line, the title, and
 *  the scale line under it. With a lede it sits beside it (split). */
export function DTitle({ no, h, id }: { no: number; h: Heading; id?: string }) {
  const title = (
    <div className="dtitle">
      <div className="no" aria-hidden="true"><span>{String(no).padStart(2, '0')}</span><i>{h.code}</i></div>
      <h2 id={id}>{h.title}</h2>
      {h.scale && <p className="scale">{h.scale}</p>}
    </div>
  )
  if (!h.lede) return title
  return <div className="split">{title}<p className="lede">{h.lede}</p></div>
}

/** "040 4005 9348" -> a tel: link's number; "+91 98480 12345" -> a wa.me number (digits only). */
export const waNumber = (raw: string) => raw.replace(/[^\d]/g, '')

export const STATE_NAMES: Record<string, string> = { AP: 'Andhra Pradesh', TS: 'Telangana', TG: 'Telangana', KA: 'Karnataka', TN: 'Tamil Nadu' }
export const stateName = (s: string) => STATE_NAMES[s.trim().toUpperCase()] ?? s.trim()
