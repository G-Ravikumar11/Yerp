import { post } from '@/lib/api'

/** What can be cleared by ticking rows. */
export type BulkKind = 'subcontract' | 'client' | 'bill' | 'vendor' | 'entry'

const PATH: Record<BulkKind, string> = {
  subcontract: '/api/wo/orders/bulk-delete',
  client: '/api/erp/work-orders/bulk-delete',
  bill: '/api/sub-bills/bulk-delete',
  vendor: '/api/wo/contractors/bulk-delete',
  entry: '/api/sub-mb/entries/bulk-delete',
}

/** How many go in one request: a work order carries a great deal with it, a measurement almost nothing. */
export const BATCH: Record<BulkKind, number> = { subcontract: 4, client: 4, bill: 8, vendor: 2, entry: 40 }

export interface BulkResult {
  deleted: number
  gone: number
  failed: { id: number; reason: string }[]
  message?: string
}

export const bulkDeleteBatch = (kind: BulkKind, ids: number[]) => post<BulkResult>(PATH[kind], { ids })
