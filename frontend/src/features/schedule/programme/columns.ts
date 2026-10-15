import type { ProgrammeRowView } from '@/api/programme'

/** The height of a row in the grid and in the chart beside it. */
export const ROW_H = 32

export type Kind = 'text' | 'number' | 'date' | null
export interface Col {
  id: 'wbs' | 'boq_ref' | 'name' | 'start' | 'end' | 'days' | 'uom' | 'quantity' | 'labour_required' | 'predecessors' | 'percent'
  label: string
  w: number
  kind: Kind
  /** Only on a row with no sub-items: a heading's dates come from its sub-items. */
  leafOnly?: boolean
  align?: 'right'
  /** Left out when the grid is narrowed to leave room for the chart. */
  extra?: boolean
  /** Said on hover over the column's heading. */
  hint?: string
}

export const COLUMNS: Col[] = [
  { id: 'wbs', label: 'SL.NO', w: 70, kind: null },
  { id: 'boq_ref', label: 'BOQ Ref', w: 76, kind: 'text', extra: true },
  { id: 'name', label: 'Item / Activity', w: 260, kind: 'text' },
  { id: 'start', label: 'Start', w: 96, kind: 'date', leafOnly: true },
  { id: 'end', label: 'End', w: 96, kind: 'date', leafOnly: true },
  { id: 'days', label: 'Days', w: 56, kind: 'number', leafOnly: true, align: 'right' },
  { id: 'uom', label: 'U.O.M', w: 60, kind: 'text', extra: true },
  { id: 'quantity', label: 'Quantity', w: 84, kind: 'number', align: 'right', extra: true },
  { id: 'labour_required', label: 'Labour', w: 64, kind: 'number', align: 'right', extra: true },
  { id: 'predecessors', label: 'Predecessor', w: 108, kind: 'text', leafOnly: true },
  { id: 'percent', label: '% Done', w: 64, kind: 'number', leafOnly: true, align: 'right' },
]

export const editableCell = (col: Col | undefined, r: ProgrammeRowView | undefined) => !!col && !!r && col.kind !== null && !(col.leafOnly && r.summary)
