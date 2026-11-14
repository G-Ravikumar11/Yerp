import { useQuery } from '@tanstack/react-query'
import { api, get } from '@/lib/api'
import { queryClient } from '@/lib/query'

/* Site stories in the phone app: the site diary's photos, site by site. A story stays in the row until the Master or an
   admin has opened it and leaves 24 hours after that; the photo itself stays in the diary (backend services/stories.py). */

export interface Story {
  /** The photo's number in the file store. */
  id: number
  url: string
  thumb_url: string
  diary_id: number
  diary_date: string
  caption: string
  /** The start of what the day's diary says was done. */
  work_done: string
  /** Who added the photo, and when. */
  by: string
  at: string
  /** Opened by the person looking. */
  seen: boolean
  /** When the Master or an admin first opened it ('' until one has), and who. */
  opened_at: string
  opened_by: string
  /** Seconds until it leaves the row; null while nobody who counts has opened it. */
  leaves_in_s: number | null
}

export interface StorySite { job_id: number; number: string; name: string; stories: Story[]; unseen: number; unopened: number; latest: string }

export interface StoryRow {
  sites: StorySite[]
  /** The person looking is the Master, an admin or staff at the Master's level: their opening starts a story's 24 hours. */
  admin: boolean
  hours: number
  unseen: number
}

export const storyKeys = { row: ['stories'] as const }

// Asked afresh each time Home is opened: a photo added to a diary a minute ago is a story now.
export const useStories = () => useQuery({ queryKey: storyKeys.row, queryFn: () => get<StoryRow>('/api/stories'), refetchOnMount: 'always', refetchInterval: 5 * 60_000 })

/**
 * The person has had this story on screen. The row is updated at once (and keeps its order, so nothing moves under a
 * story being watched); the server is told quietly. With no signal the server is not told, and the next reading of the
 * row shows the story as new again, which is the truth.
 */
export async function markStorySeen(id: number, admin: boolean, hours: number) {
  queryClient.setQueryData<StoryRow>(storyKeys.row, (row) => {
    if (!row) return row
    const sites = row.sites.map((site) => {
      if (!site.stories.some((s) => s.id === id)) return site
      const stories = site.stories.map((s) => (s.id !== id ? s : { ...s, seen: true, ...(admin && !s.opened_at ? { opened_at: 'now', opened_by: 'you', leaves_in_s: hours * 3600 } : {}) }))
      return { ...site, stories, unseen: stories.filter((s) => !s.seen).length, unopened: stories.filter((s) => !s.opened_at).length }
    })
    return { ...row, sites, unseen: sites.reduce((n, s) => n + s.unseen, 0) }
  })
  await api(`/api/stories/${id}/seen`, { method: 'POST', body: {}, quiet: true }).catch(() => undefined)
}
