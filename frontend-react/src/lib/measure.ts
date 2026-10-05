/**
 * One line of a measurement book: what was measured and how. Carried over
 * unchanged from the current app (mbdims.js), so a quantity worked out here
 * is the quantity the book has always given.
 */
export interface DimLine {
  particulars: string
  nos: number | null
  nom: number | null
  length: number | null
  breadth: number | null
  depth: number | null
  /** A deduction: the line takes quantity away. */
  deduct: boolean
  /** A heading ("Living Room", "Deductions") measures nothing. */
  heading: boolean
}

export const blankDim = (): DimLine => ({
  particulars: '',
  nos: null,
  nom: null,
  length: null,
  breadth: null,
  depth: null,
  deduct: false,
  heading: false,
})

/**
 * No's x NoM x L x B x D, over the figures that were given. A blank does not
 * apply - an area has no depth - and is not a nought. A line with no figures
 * at all measures nothing (null), and a deduction comes out negative.
 */
export function dimQty(line: DimLine): number | null {
  if (line.heading) return null
  let qty = 1
  let any = false
  for (const v of [line.nos, line.nom, line.length, line.breadth, line.depth]) {
    if (v === null || v === undefined || Number.isNaN(v)) continue
    qty *= v
    any = true
  }
  if (!any) return null
  const rounded = Math.round(qty * 1000) / 1000
  const signed = line.deduct ? -rounded : rounded
  return signed === 0 ? 0 : signed
}

/** The lines as the server takes them: a line with neither words nor a figure is left out. */
export const toApiDims = (lines: readonly DimLine[]) =>
  lines
    .filter((d) => d.particulars.trim() || [d.nos, d.nom, d.length, d.breadth, d.depth].some((v) => v !== null))
    .map((d) => ({ particulars: d.particulars, nos: d.nos, nom: d.nom, length: d.length, breadth: d.breadth, depth: d.depth, deduct: d.deduct, is_heading: d.heading }))

export function dimTotal(lines: readonly DimLine[]): number {
  const sum = lines.reduce((total, l) => total + (dimQty(l) ?? 0), 0)
  return Math.round(sum * 1000) / 1000
}

/**
 * A custom calculation, written the way it is said: `total * 5%`, `5% of total`, `(total - 12.5) / 2`.
 * `total` is what the lines above come to for one block. Only numbers, + - * / x of ( ) % and the word
 * `total` are understood; anything else gives null rather than a guess.
 */
export function evalCalc(text: string, total: number): number | null {
  const src = text
    .toLowerCase()
    .split('×').join('*')
    .split('÷').join('/')
    .split('−').join('-')
    .split(',').join('')
  const tokens: string[] = []
  const re = /\s*(\d+\.?\d*|\.\d+|total|of|[-+*/()%x])/gy
  let at = 0
  for (;;) {
    re.lastIndex = at
    const m = re.exec(src)
    if (!m) break
    tokens.push(m[1] === 'of' || m[1] === 'x' ? '*' : m[1])
    at = re.lastIndex
  }
  if (src.slice(at).trim() || !tokens.length) return null
  let i = 0
  const peek = () => tokens[i]
  const atom = (): number | null => {
    const t = tokens[i++]
    if (t === undefined) return null
    if (t === '(') {
      const v = sum()
      if (tokens[i++] !== ')') return null
      return percent(v)
    }
    if (t === '-') {
      const v = atom()
      return v === null ? null : -v
    }
    if (t === '+') return atom()
    const v = t === 'total' ? total : Number(t)
    return Number.isFinite(v) ? percent(v) : null
  }
  const percent = (v: number | null): number | null => {
    while (v !== null && peek() === '%') {
      i++
      v = v / 100
    }
    return v
  }
  const product = (): number | null => {
    let v = atom()
    while (v !== null && (peek() === '*' || peek() === '/')) {
      const op = tokens[i++]
      const r = atom()
      if (r === null || (op === '/' && r === 0)) return null
      v = op === '*' ? v * r : v / r
    }
    return v
  }
  const sum = (): number | null => {
    let v = product()
    while (v !== null && (peek() === '+' || peek() === '-')) {
      const op = tokens[i++]
      const r = product()
      if (r === null) return null
      v = op === '+' ? v + r : v - r
    }
    return v
  }
  const result = sum()
  if (result === null || i !== tokens.length || !Number.isFinite(result)) return null
  return Math.round(result * 1000) / 1000
}
