import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const stockKeys = { all: ['stock'] as const }

export interface Consumption {
  summary: { planned_value: number; issued_value: number; variance_value: number; lines_over_consumed: number; unplanned_items: number }
  lines: { item_code: string; item_name: string; planned_qty: number; issued_qty: number; variance_qty: number; variance_value: number; percent_used: number; over_consumed: boolean; unplanned: boolean }[]
}

/** A BOQ's budgeted materials against what the store issued to its project. */
export const useConsumption = (boq: number) => useQuery({ queryKey: ['stock', 'consumption', 'boq', boq], enabled: boq > 0, queryFn: () => get<Consumption>(`/api/stock/consumption/boq/${boq}`) })

export const countStock = (item_code: string, counted: number) => post<{ message: string; difference: number }>('/api/stock/adjustments', { item_code, counted, remarks: 'Physical count' })
