import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './api'
import { queryClient } from './query'

export type SessionUser = {
  type: 'owner' | 'employee'
  name: string
  email: string
  company: string
  permissions: string[]
  employeeId: number | null
  roleLabel: string
  /** The department the owner has put this person in; staff see it on their own sign-in. */
  department: string
}

type OwnerMe = { email: string; contact_name?: string; company_name?: string }
type StaffMe = {
  id: number
  email: string
  full_name?: string
  permissions?: string[]
  permission_role_label?: string
  department?: string
}

/**
 * Who is signed in - the account holder, or a member of staff. The owner
 * answers first; a 401 there means try the staff session. Either failing is
 * simply "nobody", never an exception the screens have to handle.
 */
async function loadSession(): Promise<SessionUser | null> {
  const next = await resolveSession()
  // A different person than the one this device was holding data for: what was kept for the last one is not theirs to see.
  const before = queryClient.getQueryData<SessionUser | null>(['session'])
  if (before && (!next || before.type !== next.type || before.email !== next.email)) queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'session' })
  return next
}

async function resolveSession(): Promise<SessionUser | null> {
  try {
    const owner = await api<OwnerMe>('/api/client/me', { quiet: true })
    if (owner?.email) {
      return {
        type: 'owner',
        name: owner.contact_name || owner.email,
        email: owner.email,
        company: owner.company_name || '',
        permissions: [],
        employeeId: null,
        roleLabel: 'Master',
        department: '',
      }
    }
  } catch (e) {
    if (!(e instanceof ApiError) || e.status >= 500) throw e
  }
  try {
    const staff = await api<StaffMe>('/api/employee/auth/me', { quiet: true })
    if (staff?.email) {
      return {
        type: 'employee',
        name: staff.full_name || staff.email,
        email: staff.email,
        company: '',
        permissions: staff.permissions ?? [],
        employeeId: staff.id,
        roleLabel: staff.permission_role_label || 'Staff',
        department: staff.department ?? '',
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
