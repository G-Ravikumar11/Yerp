import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

/** What the company's alerts are, as the server keeps them for the Master (low stock, a lock-out, money moving). */
export interface OwnerAlert { id: number; kind: string; title: string; body: string; severity: string; created_at: string; read: boolean }
export const alertKeys = { all: ['alerts'] as const }
export const useOwnerAlerts = (enabled: boolean) =>
  useQuery({
    queryKey: [...alertKeys.all, 'recent'],
    enabled,
    queryFn: () => get<{ alerts: OwnerAlert[]; unread: number }>('/api/alerts?limit=20'),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  })
