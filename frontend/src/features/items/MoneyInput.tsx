import { useState } from 'react'
import { Input } from '@/components/ui'
import { groupINR } from './itemLogic'

/** A rupee amount: typed plainly, shown with Indian grouping once you leave it, always on the right. */
export function MoneyInput({ id, value, onChange, disabled, invalid, placeholder }: { id: string; value: string; onChange: (v: string) => void; disabled?: boolean; invalid?: boolean; placeholder?: string }) {
  const [typing, setTyping] = useState(false)
  return (
    <Input
      id={id}
      leading="₹"
      inputMode="decimal"
      className="tabular text-right"
      value={typing ? value : groupINR(value)}
      placeholder={placeholder}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      onFocus={() => setTyping(true)}
      onBlur={() => setTyping(false)}
      onChange={(e) => {
        const t = e.target.value.replace(/,/g, '')
        if (/^\d*\.?\d{0,4}$/.test(t)) onChange(t)
      }}
    />
  )
}
