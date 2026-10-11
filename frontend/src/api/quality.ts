import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export const qcKeys = { all: ['quality'] as const }

export interface CheckItem { item: string; result: string; remark: string }
export interface Inspection { id: number; job_id: number; number: string; checklist: string; location: string; inspected_on: string; inspected_by: string; witnessed_by: string; result: string; failed_items: number; items: CheckItem[] }
export interface CubeResult { age_days: number; average: number; ok: boolean; spread_ok: boolean; verdict: string }
export interface CubeDue { age_days: number; due_on: string; overdue: boolean }
export interface CubeSet { id: number; number: string; cast_on: string; location: string; supplier: string; docket: string; grade: string; status: string; results: CubeResult[]; due: CubeDue[] }
export interface Ncr { id: number; number: string; severity: string; raised_on: string; location: string; description: string; closure_note: string; responsible: string; target_date: string; status: string; overdue: boolean }

export interface QualityData {
  inspections: Inspection[]
  cubes: CubeSet[]
  ncrs: Ncr[]
  cubeSummary: { due: number; below: number }
  ncrSummary: { open: number; overdue: number }
}

export const useChecklists = () => useQuery({ queryKey: ['quality', 'checklists'], staleTime: 10 * 60_000, queryFn: async () => (await get<{ checklists: Record<string, unknown> }>('/api/qc/checklists')).checklists })

export const useQuality = (job: number) =>
  useQuery({
    queryKey: ['quality', job],
    enabled: job >= 0,
    queryFn: async (): Promise<QualityData> => {
      const q = job ? `?job_id=${job}` : ''
      const [i, c, n] = await Promise.all([
        get<{ inspections: Inspection[] }>(`/api/qc/inspections${q}`),
        get<{ cubes: CubeSet[]; summary?: { due?: number; below?: number } }>(`/api/qc/cubes${q}`),
        get<{ ncrs: Ncr[]; summary?: { open?: number; overdue?: number } }>(`/api/qc/ncrs${q}`),
      ])
      return { inspections: i.inspections ?? [], cubes: c.cubes ?? [], ncrs: n.ncrs ?? [], cubeSummary: { due: c.summary?.due ?? 0, below: c.summary?.below ?? 0 }, ncrSummary: { open: n.summary?.open ?? 0, overdue: n.summary?.overdue ?? 0 } }
    },
  })

export const startInspection = (b: { job_id: number; checklist: string; location: string; witnessed_by: string }) => post<{ inspection: Inspection }>('/api/qc/inspections', b)
export const saveInspection = (i: Inspection) => put<{ inspection: Inspection }>(`/api/qc/inspections/${i.id}`, { job_id: i.job_id, items: i.items })
export const closeInspection = (id: number) => post<{ inspection: Inspection }>(`/api/qc/inspections/${id}/close`)
export const logCubes = (b: { job_id: number; grade: string; cast_on: string; location: string; supplier: string; docket: string; slump_mm: number }) => post<{ cube_set: { number: string } }>('/api/qc/cubes', b)
export const cubeResult = (id: number, age_days: number, strengths: string) => post<{ cube_set: CubeSet }>(`/api/qc/cubes/${id}/results`, { age_days, strengths })
export const raiseNcr = (b: Record<string, unknown>) => post<{ ncr: { number: string } }>('/api/qc/ncrs', b)
export const closeNcr = (id: number, closure_note: string) => post<{ ncr: { number: string } }>(`/api/qc/ncrs/${id}/close`, { closure_note })
