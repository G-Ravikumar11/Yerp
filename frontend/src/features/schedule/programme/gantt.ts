import { fromDay, toDay, type Calendar } from '@/lib/programme'

/** How wide a day is drawn at each zoom. */
export type Zoom = 'day' | 'week' | 'month'
export const PX_PER_DAY: Record<Zoom, number> = { day: 26, week: 9, month: 3 }

export interface Scale {
  from: number
  to: number
  px: number
  width: number
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** The span drawn: the programme with a little room each side, and today in view. */
export function scaleFor(start: string | null, finish: string | null, today: string, zoom: Zoom): Scale {
  const t = toDay(today)
  let from = start ? Math.min(toDay(start), t) - 3 : t - 14
  let to = finish ? Math.max(toDay(finish), t) + 10 : t + 60
  if (zoom === 'week') from -= ((((from + 3) % 7) + 7) % 7)        // back to a Monday (1 Jan 1970 was a Thursday)
  if (zoom === 'month') {
    const d = new Date(from * 86_400_000)
    from = toDay(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`)
    to += 30
  }
  const px = PX_PER_DAY[zoom]
  return { from, to, px, width: (to - from + 1) * px }
}

export const xOf = (s: Scale, day: number) => (day - s.from) * s.px

/** Month bands for the top line of the header. */
export function monthBands(s: Scale) {
  const out: { label: string; x: number; w: number }[] = []
  let d = s.from
  while (d <= s.to) {
    const iso = fromDay(d)
    const [y, m] = iso.split('-').map(Number)
    const next = toDay(`${m === 12 ? y + 1 : y}-${String(m === 12 ? 1 : m + 1).padStart(2, '0')}-01`)
    const end = Math.min(next - 1, s.to)
    out.push({ label: `${MONTHS[m - 1]} ${y}`, x: xOf(s, d), w: (end - d + 1) * s.px })
    d = next
  }
  return out
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** "12 Oct": a date short enough to sit beside a bar or over a week. */
export const shortDate = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`

/**
 * The second line of the header: each day at day zoom, each week (from its Monday, as "12 Oct") at week zoom, nothing
 * at month zoom, where the months are the marks. Each carries its full date, shown on hover.
 */
export function ticks(s: Scale, zoom: Zoom) {
  const out: { label: string; x: number; title: string }[] = []
  if (zoom === 'month') return out
  for (let d = s.from; d <= s.to; d++) {
    const iso = fromDay(d)
    const weekday = ((((d + 3) % 7) + 7) % 7)            // 0 is a Monday (1 Jan 1970 was a Thursday)
    const title = `${WEEKDAYS[weekday]} ${shortDate(iso)} ${iso.slice(0, 4)}`
    if (zoom === 'day') out.push({ label: String(Number(iso.slice(8, 10))), x: xOf(s, d), title })
    else if (weekday === 0) out.push({ label: shortDate(iso), x: xOf(s, d), title: `Week from ${title}` })
  }
  return out
}

/** Days off inside the span, shaded behind the bars (not drawn at month zoom, where a day is a sliver). */
export function daysOff(s: Scale, cal: Calendar, zoom: Zoom) {
  if (zoom === 'month') return []
  const out: number[] = []
  for (let d = s.from; d <= s.to; d++) if (!cal.working(d)) out.push(xOf(s, d))
  return out
}
