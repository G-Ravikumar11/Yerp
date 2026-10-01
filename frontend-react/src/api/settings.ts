import { useQuery } from '@tanstack/react-query'
import { get, post, put, del } from '@/lib/api'

export const settingsKeys = { all: ['settings'] as const }
const k = (...p: (string | number)[]) => ['settings', ...p]

/** The company's own details, as one flat set of keys. */
export type CompanySettings = Record<string, string>
export interface BankDetail {
  bank_name: string
  account_name: string
  account_number: string
  sort_code: string
}

export const useCompany = () => useQuery({ queryKey: k('company'), queryFn: () => get<CompanySettings>('/api/settings') })
export const saveCompany = (body: CompanySettings) => post<{ message?: string }>('/api/settings', body)

export const useLogo = () => useQuery({ queryKey: k('logo'), queryFn: () => get<{ logo_url: string }>('/api/client/logo') })
export const saveLogo = (logo_url: string) => put<{ message?: string }>('/api/client/logo', { logo_url })

export interface TaxRate {
  id?: number
  name: string
  percent: number
  is_default: boolean
}
export const useTaxRates = () => useQuery({ queryKey: k('tax'), queryFn: () => get<TaxRate[]>('/api/tax-rates') })
export const saveTaxRates = (tax_rates: TaxRate[]) => put<{ message?: string }>('/api/tax-rates', { tax_rates })

export interface Signatory {
  role: string
  name: string
  title: string
  image: string
  has_image?: boolean
}
export interface Signatories {
  signatories: Record<string, Signatory>
  seal: string
  has_seal?: boolean
}
export const useSignatories = () => useQuery({ queryKey: k('signatories'), queryFn: () => get<Signatories>('/api/documents/signatories') })
export const saveSignatories = (body: Record<string, unknown>) => put<{ message?: string }>('/api/documents/signatories', body)

export interface BusinessUnit {
  id: number
  name: string
  code: string
  gstin: string
  pan: string
  address: string
  logo_url: string
}
export const useBusinessUnits = () => useQuery({ queryKey: k('units'), queryFn: () => get<{ business_units: BusinessUnit[] }>('/api/wo/business-units') })
export type UnitBody = Omit<BusinessUnit, 'id'>
export const addBusinessUnit = (b: UnitBody) => post<{ message?: string }>('/api/wo/business-units', b)
export const saveBusinessUnit = (id: number, b: UnitBody) => put<{ message?: string }>(`/api/wo/business-units/${id}`, b)

export interface TermClause {
  clause_category: string
  clause_text: string
}
export const useTerms = () => useQuery({ queryKey: k('terms'), queryFn: () => get<{ library: TermClause[]; custom: boolean; standard: TermClause[] }>('/api/wo/terms/library') })
export const saveTerms = (terms: TermClause[]) => put<{ message?: string }>('/api/wo/terms/library', { terms })

export interface ApprovalRules {
  auto_below: number
  finance_above: number
  owner_signs_work_orders: boolean
  currency: string
  finance_approver: string
  has_finance_approver: boolean
}
export const useApprovalRules = () => useQuery({ queryKey: k('rules'), queryFn: () => get<ApprovalRules>('/api/approval-rules') })
export const saveApprovalRules = (b: { auto_below: number; finance_above: number; owner_signs_work_orders: boolean }) => put<{ message?: string }>('/api/approval-rules', b)

export interface WhoApproves {
  owner: string
  routes: { right: string; what: string; people: { name: string; department: string; rank: number }[] }[]
}
export const useWhoApproves = () => useQuery({ queryKey: k('who'), queryFn: () => get<WhoApproves>('/api/approvals/who-approves') })

export const useOrgDomain = () => useQuery({ queryKey: k('domain'), queryFn: () => get<{ domain: string; employees_off_domain: number }>('/api/hr/org-domain') })
export const saveOrgDomain = (domain: string) => put<{ message?: string }>('/api/hr/org-domain', { domain })

export interface TeamMember {
  id: number
  email: string
  name: string
  role: string
  is_active: boolean
  accepted: boolean
  last_login: string
  is_account_owner: boolean
}
export const useTeam = () => useQuery({ queryKey: k('team'), queryFn: () => get<{ members: TeamMember[]; your_role: string }>('/api/team') })
export const inviteMember = (b: { email: string; name: string; role: string }) => post<{ message?: string }>('/api/team/invite', b)
export const updateMember = (id: number, b: { role?: string; is_active?: boolean }) => put<{ message?: string }>(`/api/team/${id}`, b)
export const removeMember = (id: number) => del<{ message?: string }>(`/api/team/${id}`)

export interface PortalUser {
  id: number
  party_type: string
  party_id: number
  party: string
  name: string
  email: string
  is_active: boolean
  has_password: boolean
  invite_open: boolean
  invite_expires: string
  last_login: string
}
export interface PortalParty {
  id: number
  name: string
  email: string
  contact: string
}
export interface PortalAccess {
  users: PortalUser[]
  contractors: PortalParty[]
  suppliers: PortalParty[]
}
export const usePortalAccess = () => useQuery({ queryKey: k('portal'), queryFn: () => get<PortalAccess>('/api/portal-access'), staleTime: 0 })
export interface InviteResult {
  message?: string
  invite_url: string
  emailed: boolean
}
export const invitePartner = (b: { party_type: string; party_id: number; name: string; email: string }) => post<InviteResult>('/api/portal-access', b)
export const reinvitePartner = (id: number) => post<InviteResult>(`/api/portal-access/${id}/reinvite`)
export const switchPartner = (id: number, action: 'enable' | 'disable') => post<{ message?: string }>(`/api/portal-access/${id}/${action}`)

export interface AlertSettings {
  emails: string[]
  whatsapp: string[]
  channels: Record<string, string[]>
  kinds: Record<string, string>
  whatsapp_ready: boolean
  wa_phone_id: string
  wa_token_set: boolean
  email_ready: boolean
}
export const useAlertSettings = () => useQuery({ queryKey: k('alerts'), queryFn: () => get<AlertSettings>('/api/alerts/settings') })
export const saveAlertSettings = (b: { emails: string[]; whatsapp: string[]; channels: Record<string, string[]>; wa_phone_id: string; wa_token?: string }) => put<AlertSettings>('/api/alerts/settings', b)
export const sendTestAlert = () => post<{ message?: string }>('/api/alerts/test')

export interface BackupInfo {
  tables: number
  rows: number
  files: number
  files_bytes: number
  last_backup: string
  last_backup_details: string
}
export const useBackupInfo = () => useQuery({ queryKey: k('backup'), queryFn: () => get<BackupInfo>('/api/backup/info'), retry: false })

export interface AuditRow {
  id: number
  user_type: string
  user_name: string
  action: string
  entity_type: string
  entity_name: string
  details: string
  created_at: string
}
export const useAuditLog = () => useQuery({ queryKey: k('audit'), queryFn: () => get<AuditRow[]>('/api/audit-logs?limit=50') })
