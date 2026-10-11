import * as React from 'react'
import { cn } from '@/lib/utils'

const field =
  'w-full rounded-md border border-input bg-transparent px-3 text-sm text-foreground ' +
  'placeholder:text-subtle transition-[border-color,box-shadow,background-color] duration-150 ' +
  'hover:border-subtle/60 focus-visible:border-ring focus-visible:outline-none ' +
  'focus-visible:ring-4 focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:opacity-50 ' +
  'aria-[invalid=true]:border-danger aria-[invalid=true]:focus-visible:ring-danger/15'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  leading?: React.ReactNode
  trailing?: React.ReactNode
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, leading, trailing, type = 'text', ...props }, ref) => {
    if (!leading && !trailing) {
      return <input ref={ref} type={type} className={cn(field, 'h-10', className)} {...props} />
    }
    return (
      <div className="relative">
        {leading && (
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted-foreground [&_svg]:size-4">
            {leading}
          </span>
        )}
        <input
          ref={ref}
          type={type}
          className={cn(field, 'h-10', leading && 'pl-9', trailing && 'pr-9', className)}
          {...props}
        />
        {trailing && (
          <span className="absolute inset-y-0 right-3 flex items-center text-muted-foreground">{trailing}</span>
        )}
      </div>
    )
  },
)
Input.displayName = 'Input'

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(field, 'min-h-20 py-2', className)} {...props} />,
)
Textarea.displayName = 'Textarea'

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn('text-[13px] font-medium text-foreground', className)} {...props} />
}

/**
 * A number the person is typing. It keeps their own text while they type, so
 * "0." and "0.5" survive on the way, and hands over a real number only when
 * the text is one - a plain controlled number input cannot do both.
 */
export function NumField({
  value,
  onValue,
  className,
  ...props
}: Omit<InputProps, 'value' | 'onChange' | 'type'> & { value: number | null | undefined; onValue: (n: number) => void }) {
  const [text, setText] = React.useState(value ? String(value) : '')
  // Follow the outside value when it was changed from elsewhere (a reload, a reset).
  const shown = Number(text || 0)
  React.useEffect(() => {
    if ((value ?? 0) !== shown) setText(value ? String(value) : '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return (
    <Input
      {...props}
      inputMode="decimal"
      className={cn('tabular text-right', className)}
      value={text}
      onChange={(e) => {
        const t = e.target.value
        if (t !== '' && !/^-?\d*\.?\d*$/.test(t)) return
        setText(t)
        const n = t === '' || t === '-' || t === '.' ? 0 : Number(t)
        if (Number.isFinite(n)) onValue(n)
      }}
    />
  )
}

/** A label, its control and the reason it is wrong - the unit forms are built from. */
export function Field({
  label,
  hint,
  error,
  htmlFor,
  className,
  children,
}: {
  label: string
  hint?: string
  error?: string
  htmlFor?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
