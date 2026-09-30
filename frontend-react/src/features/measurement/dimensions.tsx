import type { Column } from '@/components/grid'
import { dimQty, dimTotal, type DimLine } from '@/lib/measure'

/** The dimension sheet of a measurement book: what, how many, how big - and what it comes to. */
export const dimColumns: Column<DimLine>[] = [
  { id: 'particulars', header: 'Particulars', hint: 'Slab, Beam, Deductions...', width: 260, pin: true, placeholder: 'What was measured?' },
  { id: 'nos', header: "No's", type: 'number', width: 84 },
  { id: 'nom', header: 'NoM', hint: 'Times', type: 'number', width: 84 },
  { id: 'length', header: 'Length', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'breadth', header: 'Breadth', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'depth', header: 'Depth', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'deduct', header: 'Deduct', type: 'checkbox', width: 84 },
  { id: 'heading', header: 'Heading', type: 'checkbox', width: 84 },
  {
    id: 'quantity',
    header: 'Quantity',
    hint: 'Worked out',
    type: 'number',
    decimals: 3,
    width: 130,
    readOnly: true,
    get: (r) => dimQty(r),
    summary: (rows) => dimTotal(rows).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }),
  },
]
