import { Badge } from '@/components/ui'

export type MsmeKind = 'micro' | 'small' | 'medium'
export interface Msme { type: MsmeKind | string; udyam?: string; source?: 'master' | 'declared' }

/** "MSME" beside a supplier who is registered under Udyam. Micro and small are paid within 45 days of the bill. */
export function MsmeBadge({ msme, className }: { msme?: Msme | null; className?: string }) {
  if (!msme?.type) return null
  const within45 = msme.type === 'micro' || msme.type === 'small'
  const title = [
    `${msme.type[0].toUpperCase()}${msme.type.slice(1)} enterprise`,
    msme.udyam,
    within45 ? 'pay within 45 days of the bill' : '',
    msme.source === 'declared' ? 'as the supplier said on their reply, not yet in the supplier master' : '',
  ].filter(Boolean).join(' · ')
  return (
    <Badge tone={within45 ? 'info' : 'neutral'} className={className} title={title} aria-label={`MSME: ${title}`}>
      MSME{msme.source === 'declared' ? '?' : ''}
    </Badge>
  )
}
