import { Badge } from '@/components/ui'
import type { DocStatus } from '@/api/store'

const TONE = { DRAFT: 'neutral', SUBMITTED: 'info', APPROVED: 'warning', POSTED: 'success', CANCELLED: 'danger' } as const
const LABEL: Record<DocStatus, string> = { DRAFT: 'Draft', SUBMITTED: 'Submitted', APPROVED: 'Approved', POSTED: 'Posted', CANCELLED: 'Cancelled' }

export interface DocStatusBadgeProps {
  status: DocStatus
}

/** A store document's status as a coloured pill. */
export function DocStatusBadge({ status }: DocStatusBadgeProps) {
  return <Badge tone={TONE[status] ?? 'neutral'} dot>{LABEL[status] ?? status}</Badge>
}
