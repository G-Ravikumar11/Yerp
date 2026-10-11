import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const leaveKeys = { all: ['leave'] as const }

export interface LeaveRow {
  id: number
  employee_id: number
  employee_name: string
  leave_type: string
  start_date: string
  end_date: string
  days: number
  reason: string
  status: string
  approved_by: string
}

export const useLeaveRequests = () => useQuery({ queryKey: ['leave', 'requests'], queryFn: () => get<LeaveRow[]>('/api/leave/requests') })
export const decideLeave = (id: number, action: 'approve' | 'reject') => post<{ message?: string }>(`/api/leave/requests/${id}/action`, { action })
