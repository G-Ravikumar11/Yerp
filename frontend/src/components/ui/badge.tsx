import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset',
  {
    variants: {
      tone: {
        neutral: 'bg-muted text-muted-foreground ring-border',
        ember: 'bg-primary-soft text-primary ring-primary/25',
        success: 'bg-success-soft text-success ring-success/25',
        warning: 'bg-warning-soft text-warning ring-warning/30',
        danger: 'bg-danger-soft text-danger ring-danger/25',
        info: 'bg-info-soft text-info ring-info/25',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  dot?: boolean
}

export function Badge({ className, tone, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  )
}

/** The document states the backend uses, each with its tone. */
const STATUS_TONE: Record<string, BadgeProps['tone']> = {
  DRAFT: 'neutral',
  PROVISIONAL: 'warning',
  SUBMITTED: 'warning',
  PENDING: 'warning',
  APPROVED: 'success',
  EXECUTED: 'success',
  CERTIFIED: 'info',
  PAID: 'success',
  REJECTED: 'danger',
  CANCELLED: 'danger',
  AMENDED: 'neutral',
}

export function StatusBadge({ status }: { status: string }) {
  const key = status.toUpperCase()
  return (
    <Badge tone={STATUS_TONE[key] ?? 'neutral'} dot>
      {status.charAt(0).toUpperCase() + status.slice(1).toLowerCase()}
    </Badge>
  )
}
