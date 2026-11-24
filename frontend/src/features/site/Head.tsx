import type { Heading } from './data/content'

/** A section's heading as Settings -> Website sets it: the small line, the heading, and the line beside it if there is one. */
export function Head({ h, lede }: { h: Heading; lede?: string }) {
  const side = lede ?? h.lede
  return (
    <div className="sechead sechead--split">
      <div><p className="eyebrow">{h.eyebrow}</p><h2 className="h2">{h.title}</h2></div>
      {side && <p className="lede">{side}</p>}
    </div>
  )
}
