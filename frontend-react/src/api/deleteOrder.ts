import { useQuery } from '@tanstack/react-query'
import { del, get } from '@/lib/api'

/** The two kinds of work order: the ones given to gangs, and the ones received from clients. */
export type OrderKind = 'subcontract' | 'client'
const base = (kind: OrderKind, id: number) => (kind === 'subcontract' ? `/api/wo/orders/${id}` : `/api/erp/work-orders/${id}`)

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
