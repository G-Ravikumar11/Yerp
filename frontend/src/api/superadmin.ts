import { useQuery } from '@tanstack/react-query'
import { api, del, get, post, put } from '@/lib/api'

export interface SaMe { username: string }
export interface Insights { total_clients: number; active_clients: number; total_invoices: number; total_outstanding: number }
export interface PlatformStats {
  hr: { employees: number; departments: number; payslips: number; payroll_paid: number }
  recruitment: { open_jobs: number; applications: number }
  tenants: { active_last_30_days: number; total: number }
}
export interface Revenue { symbol: string; total_topped_up: number; total_consumed: number; outstanding_liability: number; by_action: { action_key: string; revenue: number }[] }
export interface Gateways { providers: { key: string; enabled: boolean }[] }
export interface PriceRow { id: number; label: string; module: string; action_key: string; unit_price: number; free_allowance: number }
export interface WalletRow { client_id: number; company_name: string; lifetime_spent: number; balance: number; is_low: boolean }
export interface SaClient { id: number; company_name?: string; contact_name?: string; email: string; is_active: boolean; is_onboarded: boolean; invoice_count?: number; outstanding?: number; created_at?: string; login_count?: number }
export interface SaClientDetail extends SaClient { phone_number?: string; address?: string; abn?: string; industry?: string; invoices?: { number: string; status: string; due?: number; date?: string }[] }
export interface ClientOverview {
  invoicing: { invoices: number; collected: number; outstanding: number; overdue_count: number }
  hr: { employees: number; active_employees: number; departments: number; pending_leave: number }
  recruitment: { jobs: number; open_jobs: number; applications: number; interviews: number }
  portals: { employee: string; job_board: string }
}
export interface Trends { months: string[]; revenue: number[]; active_users: number[]; total_revenue: number }
export interface LoginStats { today_logins: number; week_logins: number; failed_logins: number; clients_never_logged_in: number }
export interface LoginLog { email: string; user_type: string; login_type: string; ip_address?: string; status: string; created_at?: string }

/** Every company's errors with their tracebacks, and whether server faults are spiking (the platform admin only). */
export interface SaError { id: number; at: string; code: string; ref: string; status: number; method: string; path: string; detail: string; who: string; client_id: number | null; company: string; trace: string }
export interface SaErrors { errors: SaError[]; areas: Record<string, string>; days: number; spike: { last_hour: number; usual_per_hour: number; threshold: number; spiking: boolean } }

const useSa = <T,>(key: string, url: string, enabled = true) => useQuery({ queryKey: ['sa', key, url], queryFn: () => get<T>(url), enabled, retry: false })

export const useSaMe = () => useQuery({ queryKey: ['sa', 'me'], queryFn: () => api<SaMe>('/api/superadmin/me', { quiet: true }).catch(() => null), retry: false })
export const useInsights = () => useSa<Insights>('insights', '/api/superadmin/insights')
export const usePlatformStats = () => useSa<PlatformStats>('platform', '/api/superadmin/platform-stats')
export const useRevenue = () => useSa<Revenue>('revenue', '/api/superadmin/revenue')
export const useGateways = () => useSa<Gateways>('gateways', '/api/superadmin/gateways')
export const usePricing = () => useSa<PriceRow[]>('pricing', '/api/superadmin/pricing')
export const useWallets = () => useSa<WalletRow[]>('wallets', '/api/superadmin/wallets')
export const useSaClients = () => useSa<SaClient[]>('clients', '/api/superadmin/clients')
export const useSaClient = (id: number) => useSa<SaClientDetail>('client', `/api/superadmin/clients/${id}`, id > 0)
export const useClientOverview = (id: number) => useSa<ClientOverview>('overview', `/api/superadmin/clients/${id}/overview`, id > 0)
export const useTrends = () => useSa<Trends>('trends', '/api/superadmin/trends')
export const useLoginStats = () => useSa<LoginStats>('loginstats', '/api/superadmin/login-stats')
export const useSaErrors = (area: string, q: string) => useSa<SaErrors>('errors', `/api/superadmin/errors?days=7${area ? `&area=${area}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const useLoginLogs = () => useSa<LoginLog[]>('loginlogs', '/api/superadmin/login-logs?limit=100')

export const saKeys = { all: ['sa'] as const }
export const savePrice = (id: number, unit_price: number, free_allowance: number) => put<{ message: string }>(`/api/superadmin/pricing/${id}`, { unit_price, free_allowance })
export const adjustWallet = (clientId: number, amount: number, reason: string) => post<{ balance: number }>(`/api/superadmin/wallets/${clientId}/adjust`, { amount, reason })
export const toggleClient = (id: number) => put<{ message?: string }>(`/api/superadmin/clients/${id}/toggle`)
export const deleteClient = (id: number) => del<{ message?: string }>(`/api/superadmin/clients/${id}`)
export const impersonate = (id: number) => post<{ message?: string }>(`/api/superadmin/impersonate/${id}`)
export const changePassword = (new_password: string) => post<{ message?: string }>('/api/superadmin/change-password', { new_password })
export const saLogout = () => post<{ message?: string }>('/api/superadmin/logout')
