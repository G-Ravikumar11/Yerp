import { useQuery } from '@tanstack/react-query'
import { api, get } from '@/lib/api'

/** Settings > Error log: every error the app answered with, newest first (the Master only). */
export interface LoggedError {
  id: number
  at: string
  code: string
  title: string
  ref: string
  status: number
  method: string
  path: string
  detail: string
  who: string
  /** Empty for a company: the traceback is the platform's, read by its admin. */
  trace: string
  /** A traceback is kept for this one - quote the ref to the platform team. */
  has_trace?: boolean
}
export interface ErrorLog { errors: LoggedError[]; areas: Record<string, string>; summary: { total: number; by_area: Record<string, number>; days: number } }

export const useErrorLog = (area: string, q: string, days: number) =>
  useQuery({
    queryKey: ['error-log', area, q, days],
    queryFn: () => get<ErrorLog>(`/api/errors?days=${days}${area ? `&area=${area}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  })

/** A screen crashed (YE-APP): tell the server, so it shows in the error log. Never throws: it is a report, not a task. */
export function reportScreenFault(ref: string, message: string, stack: string) {
  void api('/api/errors/report', { method: 'POST', quiet: true, body: { ref, path: location.pathname, message: message.slice(0, 1000), stack: stack.slice(-8000) } }).catch(() => undefined)
}
