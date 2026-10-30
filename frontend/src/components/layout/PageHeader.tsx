import * as React from 'react'

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
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="text-gradient mb-1.5 w-fit text-xs font-semibold uppercase tracking-[0.14em]">{eyebrow}</p>}
        <h1 className="title-gradient w-fit max-w-full text-balance text-3xl font-semibold leading-tight sm:text-[2rem]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-[15px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
