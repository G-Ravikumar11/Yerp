import { useIdentity } from '@/api/identity'
import { cn } from '@/lib/utils'

/** The company's logo where it has one; its initials on the brand colour where it has not. */
export function CompanyMark({ className }: { className?: string }) {
  const { data } = useIdentity()
  if (data?.logo_url) {
    return (
      <span className={cn('grid shrink-0 place-items-center overflow-hidden rounded-xl bg-white ring-1 ring-border', className)}>
        <img src={data.logo_url} alt={data.name ? `${data.name} logo` : 'Company logo'} className="size-full object-contain p-0.5" />
      </span>
    )
  }
  const letters = (data?.name || 'Y')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
  return (
    <span className={cn('grid shrink-0 place-items-center rounded-xl bg-gradient-to-br from-ember-300 to-ember-600 text-sm font-semibold text-white shadow-glow', className)} aria-hidden>
      {letters}
    </span>
  )
}
