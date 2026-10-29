import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './api'
import { queryClient } from './query'

type SessionUser = {
  type: 'owner' | 'employee'
  name: string
  email: string
  company: string
  permissions: string[]
  employeeId: number | null
  roleLabel: string
  /** owner, admin or viewer for the company login; empty for staff. Only the owner is the Master. */
  teamRole: string
  /** The access level's code - 'ho_qs', 'planning_billing' and so on. 'owner' for the company login. */
  roleCode: string
  /** HO QS or HO Coordinator: they land on the HO portal rather than a site's day. */
  headOffice: boolean
  /** The department the owner has put this person in; staff see it on their own sign-in. */
  department: string
}

type OwnerMe = { email: string; contact_name?: string; company_name?: string; role?: string }
type StaffMe = {
  id: number
  email: string
  full_name?: string
  permissions?: string[]
  permission_role?: string
  permission_role_label?: string
  head_office?: boolean
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

// Staff are most of the people who sign in, and the owner's door answers them with a refusal first - a whole request
// before the app even starts. The door that worked last time is tried first; the other is still tried if it fails.
const DOOR_KEY = 'yerp-door'
const lastDoor = (): string => { try { return localStorage.getItem(DOOR_KEY) ?? '' } catch { return '' } }
const rememberDoor = (type: string) => { try { localStorage.setItem(DOOR_KEY, type) } catch { /* private window: nothing to remember */ } }

const asOwner = async (): Promise<SessionUser | null> => {
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
        roleLabel: owner.role && owner.role !== 'owner' ? (owner.role === 'viewer' ? 'Viewer' : 'Admin') : 'Master',
        teamRole: owner.role || 'owner',
        roleCode: 'owner',
        headOffice: false,
        department: '',
      }
    }
  } catch (e) {
    if (!(e instanceof ApiError) || e.status >= 500) throw e
  }
  return null
}

const asStaff = async (): Promise<SessionUser | null> => {
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
        teamRole: '',
        roleCode: staff.permission_role || 'staff',
        headOffice: !!staff.head_office,
        department: staff.department ?? '',
      }
    }
  } catch (e) {
    if (!(e instanceof ApiError) || e.status >= 500) throw e
  }
  return null
}

/** Rights a team member never gets, however much they otherwise can do. */
const HR_AND_MASTER_ONLY = new Set(['payroll.manage'])

async function resolveSession(): Promise<SessionUser | null> {
  const order = lastDoor() === 'employee' ? [asStaff, asOwner] : [asOwner, asStaff]
  for (const door of order) {
    const found = await door()
    if (found) { rememberDoor(found.type); return found }
  }
  return null
}

export function useSession() {
  const q = useQuery({ queryKey: ['session'], queryFn: loadSession, staleTime: 5 * 60_000, retry: false })
  const user = q.data ?? null

  /** "a|b" means either will do. The owner holds everything, including rights added later. The payroll right is the exception
   *  for a team member the Master has invited: payroll is HR's and the Master's alone, whatever role they were given. */
  const can = (permission: string) => {
    if (!user) return false
    if (user.type === 'owner') return user.teamRole === 'owner' || permission.split('|').some((p) => !HR_AND_MASTER_ONLY.has(p))
    return permission.split('|').some((p) => user.permissions.includes(p))
  }

  return {
    user,
    can,
    isLoading: q.isPending,
    // Only an answer of "nobody" is signed out. No answer at all (no signal) is not.
    isAnonymous: q.isSuccess && !user,
    isOwner: user?.type === 'owner' && user.teamRole === 'owner',
    /** The Master, or a staff login that holds HR's right: the people's ID numbers, their documents, payroll and the salary structure. */
    isHrOrMaster: user?.type === 'owner' ? user.teamRole === 'owner' : !!user?.permissions.includes('people.manage'),
    /** HO QS or HO Coordinator. */
    isHeadOffice: !!user?.headOffice,
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
