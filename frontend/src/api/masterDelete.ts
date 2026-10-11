import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

/**
 * The kinds of record the Master can delete, each with what hangs off it. "project" is the whole project;
 * the rest go through one door on the server (/api/master/...).
 */
export type MasterKind =
  | 'project' | 'purchase_order' | 'grn' | 'rfq' | 'supplier_bill' | 'invoice' | 'quote' | 'estimate' | 'lead' | 'ra_bill'
  | 'variation_order' | 'boq_variation' | 'boq' | 'budget' | 'drawing' | 'diary' | 'inspection' | 'cube_set' | 'ncr' | 'incident'
  | 'toolbox' | 'permit' | 'supplier' | 'item' | 'equipment' | 'activity' | 'stock_issue' | 'eway' | 'payment' | 'thread' | 'retention_release' | 'attendance'

const base = (kind: MasterKind, id: number) => (kind === 'project' ? `/api/jobs/${id}` : `/api/master/${kind}/${id}`)

export interface MasterPreview {
  numbers: string[]
  noun?: string
  counts: Record<string, number>
  /** Kept, with their link to it cleared (a project only). */
  kept?: Record<string, number>
  blockers: string[]
  warnings: string[]
  can_delete: boolean
}

export const useMasterPreview = (kind: MasterKind, id: number, enabled: boolean) =>
  useQuery({ queryKey: ['master-preview', kind, id], queryFn: () => get<MasterPreview>(`${base(kind, id)}/delete-preview`), enabled: enabled && id > 0, gcTime: 0, staleTime: 0 })

export const masterDelete = (kind: MasterKind, id: number) => del<{ message?: string }>(base(kind, id))
export const masterBulkDelete = (kind: Exclude<MasterKind, 'project'>, ids: number[]) =>
  post<{ deleted: number; gone: number; failed: { id: number; reason: string }[]; message?: string }>(`/api/master/${kind}/bulk-delete`, { ids })
