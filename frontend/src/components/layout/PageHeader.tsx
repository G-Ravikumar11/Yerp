import * as React from 'react'
import { useShellTitle } from '@/lib/shellTitle'

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
  eyebrow?: string
}) {
  // On the phone the top bar already says what this screen is: its eyebrow and heading would only say it again.
  const said = useShellTitle() === title
  return (
    <div className={said ? 'mb-4 flex flex-wrap items-end justify-between gap-3' : 'mb-8 flex flex-wrap items-end justify-between gap-4'}>
      <div className="min-w-0">
        {!said && eyebrow && <p className="text-gradient mb-1.5 w-fit text-xs font-semibold uppercase tracking-[0.14em]">{eyebrow}</p>}
        {!said && <h1 className="title-gradient w-fit max-w-full text-balance text-3xl font-semibold leading-tight sm:text-[2rem]">{title}</h1>}
        {description && <p className={said ? 'max-w-2xl text-[15px] text-muted-foreground' : 'mt-2 max-w-2xl text-[15px] text-muted-foreground'}>{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
