import { useQuery } from '@tanstack/react-query'
import { ApiError, get } from './api'

export type SessionUser = {
  type: 'owner' | 'employee'
  name: string
  email: string
  company: string
  permissions: string[]
  employeeId: number | null
  roleLabel: string
}

type OwnerMe = { email: string; contact_name?: string; company_name?: string }
type StaffMe = {
  id: number
  email: string
  full_name?: string
  permissions?: string[]
  permission_role_label?: string
}

/**
 * Who is signed in - the account holder, or a member of staff. The owner
 * answers first; a 401 there means try the staff session. Either failing is
 * simply "nobody", never an exception the screens have to handle.
 */
async function loadSession(): Promise<SessionUser | null> {
  try {
    const owner = await get<OwnerMe>('/api/client/me')
    if (owner?.email) {
      return {
        type: 'owner',
        name: owner.contact_name || owner.email,
        email: owner.email,
        company: owner.company_name || '',
        permissions: [],
        employeeId: null,
        roleLabel: 'Owner',
      }
    }
  } catch (e) {
    if (!(e instanceof ApiError) || e.status >= 500) throw e
  }
  try {
    const staff = await get<StaffMe>('/api/employee/auth/me')
    if (staff?.email) {
      return {
        type: 'employee',
        name: staff.full_name || staff.email,
        email: staff.email,
        company: '',
        permissions: staff.permissions ?? [],
        employeeId: staff.id,
        roleLabel: staff.permission_role_label || 'Staff',
      }
    }
  } catch (e) {
    if (!(e instanceof ApiError) || e.status >= 500) throw e
  }
  return null
}

export function useSession() {
  const q = useQuery({ queryKey: ['session'], queryFn: loadSession, staleTime: 5 * 60_000, retry: false })
  const user = q.data ?? null

  /** "a|b" means either will do. The owner holds everything, including rights added later. */
  const can = (permission: string) => {
    if (!user) return false
    if (user.type === 'owner') return true
    return permission.split('|').some((p) => user.permissions.includes(p))
  }

  return {
    user,
    can,
    isLoading: q.isPending,
    // Only an answer of "nobody" is signed out. No answer at all (no signal) is not.
    isAnonymous: q.isSuccess && !user,
    isOwner: user?.type === 'owner',
    // A failed refresh with a person already known (offline, or the server restarting) is not
    // "could not reach the server" - the person is still there, and so is their data.
    error: user ? null : q.error,
  }
}

export function initials(name: string | undefined) {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  return ((parts[0][0] ?? '') + (parts.length > 1 ? (parts[parts.length - 1][0] ?? '') : '')).toUpperCase()
}
