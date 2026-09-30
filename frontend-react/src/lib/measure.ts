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

export function dimTotal(lines: readonly DimLine[]): number {
  const sum = lines.reduce((total, l) => total + (dimQty(l) ?? 0), 0)
  return Math.round(sum * 1000) / 1000
}
