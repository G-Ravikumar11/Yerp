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
  // Not yet loaded, or no logo given: the Y, the same picture as the tab icon.
  return (
    <span className={cn('grid shrink-0 place-items-center overflow-hidden rounded-xl bg-white ring-1 ring-border', className)}>
      <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="Y ERP" className="size-full object-contain" />
    </span>
  )
}
