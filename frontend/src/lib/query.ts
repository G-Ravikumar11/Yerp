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

/* --- Kept on the device ------------------------------------------------------
   What was last read is written to IndexedDB, so a screen opened with no signal
   still has something to show. It is cleared on sign-out, and each build has
   its own stamp so data saved by an older one is never trusted by a newer.   */

import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { del, get as idbGet, set as idbSet } from 'idb-keyval'

declare const __BUILD__: string

export const persister = createAsyncStoragePersister({
  key: 'yerp-query-cache',
  throttleTime: 1500,
  storage: {
    getItem: (key) => idbGet(key),
    setItem: (key, value) => idbSet(key, value),
    removeItem: (key) => del(key),
  },
})

export const persistOptions = {
  persister,
  maxAge: 24 * 60 * 60 * 1000,
  buster: typeof __BUILD__ === 'undefined' ? 'dev' : __BUILD__,
  dehydrateOptions: {
    // What was read and is still held - including a query whose refresh has just failed for want of signal, which keeps its last answer.
    // Never one with nothing to show.
    shouldDehydrateQuery: (q: { state: { status: string; data: unknown } }) => q.state.data !== undefined && q.state.status !== 'pending',
  },
}

/** Everything this device is holding for the signed-in person. Called on sign-out. */
export async function forgetLocalData() {
  queryClient.clear()
  await persister.removeClient()
}
