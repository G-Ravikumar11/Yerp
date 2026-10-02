import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
import { useSession } from '@/lib/session'

/**
 * The company as its documents show it: one record, read once, used everywhere - the sidebar, the
 * notice about what is missing, the settings checklist. It lives under the settings keys, so saving
 * the company, its logo or a letterhead refreshes it.
 */
export interface Identity {
  name: string
  code: string
  address: string
  gstin: string
  pan: string
  state: string
  logo_url: string
  /** The mandatory details still not given, in words: "GSTIN", "logo". */
  missing: string[]
}

export function useIdentity() {
  const { user } = useSession()
  return useQuery({ queryKey: ['settings', 'identity'], queryFn: () => get<Identity>('/api/company/identity'), enabled: !!user, retry: false })
}

/** What every document must carry, in the order people look for it. */
export const MANDATORY: { key: keyof Identity; label: string }[] = [
  { key: 'name', label: 'Company name' },
  { key: 'address', label: 'Address' },
  { key: 'gstin', label: 'GSTIN' },
  { key: 'pan', label: 'PAN' },
  { key: 'logo_url', label: 'Logo' },
]
