import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './api'

/**
 * Site engineers work on poor connections, so the defaults lean on the cache:
 * data is served from it immediately and refreshed in the background, queries
 * keep retrying quietly rather than failing loudly, and the cache is kept a
 * day so a screen opened in a basement still has something to show. The
 * persistence layer that writes it to storage comes in the offline step.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 24 * 60 * 60 * 1000,
      networkMode: 'offlineFirst',
      refetchOnWindowFocus: false,
      retry: (count, error) => {
        // A refused request will be refused again; a dropped one may not be.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return count < 3
      },
    },
    mutations: { networkMode: 'offlineFirst' },
  },
})
