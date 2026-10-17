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

const factorOf = (uom: string, uoms: UomOption[]) => uoms.find((u) => u.code.toLowerCase() === uom.toLowerCase())?.to_base_factor

/** The quantity in base units, for display only (the server converts for real). */
export function baseQty(qty: string, uom: string, uoms: UomOption[]): string | null {
  const n = Number(qty)
  const factor = factorOf(uom, uoms)
  if (!qty.trim() || !Number.isFinite(n) || !factor) return null
  return (n * factor).toFixed(3)
}

/** "1 bag = 50 kg", "1 nos = 10.667 kg": what one of the unit is, for the line under the box. */
export function unitHint(uom: string, base: string, uoms: UomOption[]): string | null {
  const factor = factorOf(uom, uoms)
  if (!factor || !base || uom.toLowerCase() === base.toLowerCase()) return null
  return `1 ${uom} = ${Number(factor.toFixed(3))} ${base}`
}

/** A quantity typed with a comma for thousands or a stray space, cleaned to what the box accepts - or null. */
export function cleanQty(typed: string): string | null {
  const t = typed.replace(/[\s,]/g, '')
  return /^\d*\.?\d{0,3}$/.test(t) ? t : null
}

/** A quantity and the unit it is counted in, with the item's own units to pick from. */
export function UomQtyInput({ itemId, value, onChange, showBase = true, disabled, ...rest }: UomQtyInputProps) {
  const q = useItemUoms(itemId)
  const uoms = q.data?.uoms ?? []
  const base = q.data?.base_uom
  // A unit the item does not have (left over from the item chosen before) shows as the base unit.
  const known = !!value.uom && uoms.some((u) => u.code.toLowerCase() === value.uom.toLowerCase())
  const uom = (known || !uoms.length ? value.uom : '') || base || ''
  const shown = showBase && base && uom.toLowerCase() !== base.toLowerCase() ? baseQty(value.qty, uom, uoms) : null
  const hint = base ? unitHint(uom, base, uoms) : null
  return (
    <div>
      <div className="flex gap-2">
        <Input
          inputMode="decimal"
          aria-invalid={rest['aria-invalid']}
          aria-label={uom ? `Quantity in ${uom}` : 'Quantity'}
          className="min-w-0 flex-1 text-right tabular"
          placeholder="0.000"
          disabled={disabled || !itemId}
          value={value.qty}
          onChange={(e) => {
            const t = cleanQty(e.target.value)
            if (t !== null) onChange({ qty: t, uom })
          }}
          onKeyDown={(e) => {
            // Alt+Down / Alt+Up steps through the units without leaving the quantity.
            if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && uoms.length > 1) {
              e.preventDefault()
              const i = uoms.findIndex((u) => u.code.toLowerCase() === uom.toLowerCase())
              const next = uoms[(i + (e.key === 'ArrowDown' ? 1 : uoms.length - 1)) % uoms.length]
              onChange({ qty: value.qty, uom: next.code })
            }
          }}
        />
        <div className="w-28 shrink-0">
          <Select
            disabled={disabled || !itemId || uoms.length < 2}
            aria-label="Unit"
            title={uoms.length > 1 ? 'Alt+Up / Alt+Down in the quantity changes the unit' : undefined}
            value={uom}
            options={(uoms.length ? uoms : uom ? [{ code: uom, to_base_factor: 1 }] : []).map((u) => ({ value: u.code, label: u.code }))}
            onChange={(e) => onChange({ ...value, uom: e.target.value })}
          />
        </div>
      </div>
      {(shown || hint) && (
        <p className="mt-1 text-right text-xs text-muted-foreground">
          {shown ? `= ${shown} ${base}` : null}
          {shown && hint ? ' · ' : null}
          {hint}
        </p>
      )}
    </div>
  )
}
