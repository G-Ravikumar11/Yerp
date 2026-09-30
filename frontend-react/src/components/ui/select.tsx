import * as React from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SelectOption {
  value: string | number
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  options: readonly SelectOption[]
  /** The first, empty choice - "Choose a project". Omit for a select that always has an answer. */
  placeholder?: string
}

/** The browser's own select - so it works with every keyboard and phone - dressed to match. */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ options, placeholder, className, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        'h-10 w-full appearance-none rounded-md border border-input bg-transparent pl-3 pr-9 text-sm text-foreground',
        'transition-[border-color,box-shadow] duration-150 hover:border-subtle/60',
        'focus-visible:border-ring focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/15',
        'disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-danger',
        className,
      )}
      {...props}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled} className="bg-popover text-foreground">
          {o.label}
        </option>
      ))}
    </select>
    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
  </div>
))
Select.displayName = 'Select'
