import { Input, Select } from '@/components/ui'
import { useItemUoms, type UomOption } from '@/api/store'

export interface UomQtyValue {
  /** Kept as typed ("12.5"). The server converts and rounds; never do sums on this. */
  qty: string
  uom: string
}

export interface UomQtyInputProps {
  /** Which item's units to offer. Nothing is offered until one is chosen. */
  itemId: number | null
  value: UomQtyValue
  onChange: (next: UomQtyValue) => void
  /** Show what the quantity comes to in the item's base unit ("= 150.000 kg"). */
  showBase?: boolean
  disabled?: boolean
  'aria-invalid'?: boolean
}

/** The quantity in base units, for display only (the server converts for real). */
export function baseQty(qty: string, uom: string, uoms: UomOption[]): string | null {
  const n = Number(qty)
  const factor = uoms.find((u) => u.code.toLowerCase() === uom.toLowerCase())?.to_base_factor
  if (!qty.trim() || !Number.isFinite(n) || !factor) return null
  return (n * factor).toFixed(3)
}

/** A quantity and the unit it is counted in, with the item's own units to pick from. */
export function UomQtyInput({ itemId, value, onChange, showBase = true, disabled, ...rest }: UomQtyInputProps) {
  const q = useItemUoms(itemId)
  const uoms = q.data?.uoms ?? []
  const base = q.data?.base_uom
  const uom = value.uom || base || ''
  const shown = showBase && base && uom.toLowerCase() !== base.toLowerCase() ? baseQty(value.qty, uom, uoms) : null
  return (
    <div>
      <div className="flex gap-2">
        <Input
          inputMode="decimal"
          aria-invalid={rest['aria-invalid']}
          className="min-w-0 flex-1 text-right"
          placeholder="0.000"
          disabled={disabled || !itemId}
          value={value.qty}
          onChange={(e) => {
            if (/^\d*\.?\d{0,3}$/.test(e.target.value)) onChange({ qty: e.target.value, uom })
          }}
        />
        <div className="w-28 shrink-0">
          <Select
            disabled={disabled || !itemId}
            aria-label="Unit"
            value={uom}
            options={uoms.map((u) => ({ value: u.code, label: u.code }))}
            onChange={(e) => onChange({ ...value, uom: e.target.value })}
          />
        </div>
      </div>
      {shown && (
        <p className="mt-1 text-right text-xs text-muted-foreground">
          = {shown} {base}
        </p>
      )}
    </div>
  )
}
