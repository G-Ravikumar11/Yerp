import { useQuery } from '@tanstack/react-query'
import { del, get } from '@/lib/api'

/** What can be deleted: a gang's work order, a client's, an RA bill, or a vendor with everything of theirs. */
export type OrderKind = 'subcontract' | 'client' | 'bill' | 'vendor'
const base = (kind: OrderKind, id: number) =>
  kind === 'subcontract' ? `/api/wo/orders/${id}` : kind === 'client' ? `/api/erp/work-orders/${id}` : kind === 'bill' ? `/api/sub-bills/${id}` : `/api/wo/contractors/${id}`

export interface DeletePreview {
  numbers: string[]
  counts: Record<string, number>
  blockers: string[]
  warnings: string[]
  can_delete: boolean
}

export const useDeletePreview = (kind: OrderKind, id: number, enabled: boolean) =>
  useQuery({ queryKey: ['delete-preview', kind, id], queryFn: () => get<DeletePreview>(`${base(kind, id)}/delete-preview`), enabled: enabled && id > 0, gcTime: 0, staleTime: 0 })

export const deleteWorkOrder = (kind: OrderKind, id: number) => del<{ message?: string }>(base(kind, id))
