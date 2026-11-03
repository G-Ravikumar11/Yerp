import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export type AnnouncementKind = 'general' | 'site' | 'holiday' | 'important'

/** A photo or a video shown with an announcement. */
export interface AnnouncementMedia { id: number; kind: 'image' | 'video'; name: string; content_type: string; size: number; url: string }

/** What a post may hold: up to six, photos to 10 MB and videos to 50 MB. */
export const MEDIA_MAX = 6
export const IMAGE_MAX_MB = 10
export const VIDEO_MAX_MB = 50

/** Something HR wants every employee to read. */
export interface Announcement {
  id: number
  title: string
  body: string
  category: AnnouncementKind
  pinned: boolean
  /** The last day it shows (YYYY-MM-DD), or empty. */
  expires_on: string
  /** Past its last day: staff no longer see it; HR does, marked. */
  expired: boolean
  posted_by: string
  created_at: string
  updated_at: string
  can_edit: boolean
  media: AnnouncementMedia[]
}
export interface AnnouncementFeed { announcements: Announcement[]; can_post: boolean; categories: AnnouncementKind[] }
export interface AnnouncementInput { title: string; body: string; category: AnnouncementKind; pinned: boolean; expires_on: string; notify?: boolean }

export const feedKeys = { all: ['feed'] as const }

/** Set once the Feed has been shown this session, so the front page sends people to it only the first time. */
export const FEED_SEEN = 'yerp-feed-seen'

export const useAnnouncements = () => useQuery({
  queryKey: feedKeys.all,
  queryFn: () => get<AnnouncementFeed>('/api/announcements'),
  refetchInterval: 60_000,
})

export const postAnnouncement = (b: AnnouncementInput) => post<Announcement & { told: number }>('/api/announcements', b)
export const changeAnnouncement = (id: number, b: AnnouncementInput) => put<Announcement>(`/api/announcements/${id}`, b)
export const pinAnnouncement = (id: number, pinned: boolean) => post<{ id: number; pinned: boolean }>(`/api/announcements/${id}/pin`, { pinned })
export const removeAnnouncement = (id: number) => del<{ message: string }>(`/api/announcements/${id}`)

export const addAnnouncementMedia = (id: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return post<AnnouncementMedia>(`/api/announcements/${id}/media`, form)
}
export const removeAnnouncementMedia = (id: number, mediaId: number) => del<{ message: string }>(`/api/announcements/${id}/media/${mediaId}`)
