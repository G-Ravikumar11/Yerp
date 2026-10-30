import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

export interface Reaction { emoji: string; count: number; mine: boolean; names: string[] }
export interface Wish { id: number; author: string; message: string; at: string; mine: boolean; can_delete: boolean }

/** Something to celebrate: a colleague's birthday, a festival, or a day HR added. `key` is what reactions and messages hang from. */
export interface Celebration {
  key: string
  kind: 'birthday' | 'festival' | 'special'
  date: string
  title: string
  emoji: string
  message: string
  employee_id?: number
  employee_name?: string
  job_title?: string
  special_id?: number
}
export interface TodayCelebration extends Celebration { reactions: Reaction[]; wishes: Wish[] }
export interface UpcomingCelebration extends Celebration { days_away: number }
export interface CelebrationFeed { today: TodayCelebration[]; upcoming: UpcomingCelebration[]; emojis: string[]; can_manage: boolean }
export interface SpecialDay { id: number; date: string; name: string; message: string; emoji: string; yearly: boolean }

export const celebrationKeys = { all: ['celebrations'] as const, special: ['celebrations', 'special-days'] as const }

export const useCelebrations = () => useQuery({
  queryKey: celebrationKeys.all,
  queryFn: () => get<CelebrationFeed>('/api/celebrations'),
  refetchInterval: 60_000,
})
export const useSpecialDays = (enabled: boolean) => useQuery({
  queryKey: celebrationKeys.special,
  queryFn: () => get<SpecialDay[]>('/api/celebrations/special-days'),
  enabled,
})

export const react = (celebration: string, emoji: string) => post<{ reacted: boolean }>('/api/celebrations/react', { celebration, emoji })
export const addWish = (celebration: string, message: string) => post<{ id: number }>('/api/celebrations/wishes', { celebration, message })
export const removeWish = (id: number) => del<{ message: string }>(`/api/celebrations/wishes/${id}`)
export const addSpecialDay = (b: { date: string; name: string; message: string; emoji: string; yearly: boolean }) =>
  post<SpecialDay & { announced: number }>('/api/celebrations/special-days', b)
export const removeSpecialDay = (id: number) => del<{ message: string }>(`/api/celebrations/special-days/${id}`)
