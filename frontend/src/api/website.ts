import { useQuery } from '@tanstack/react-query'
import { api, del, get, post, put } from '@/lib/api'

/** One section of the company website, as kept in Settings -> Website: what visitors see (`published`) and what is being
 *  worked on (`draft`), each in the shape the site's data/content.ts gives it. */
export interface WebsiteSection {
  key: string
  label: string
  draft: unknown
  published: unknown
  unpublished_changes: boolean
  updated_at: string
  updated_by: string
  published_at: string
  published_by: string
}

export interface WebsiteVersion { id: number; number: number; note: string; published_at: string; published_by: string }

/** A project's card on the website. `photos` null: the newest photos of the project, up to the most allowed. */
export interface ProjectCard { show: boolean; sector: string; location: string; scope: string; photos: number[] | null }
export interface WebsiteProject { id: number; number: string; name: string; client: string; status: string; published: ProjectCard; draft: ProjectCard; photos: number[] }

export type Place = 'hero' | 'section' | 'story' | 'project'
export interface WebsiteImage { id: number; name: string; place: Place; created_at: string; size: number; path: string; published: boolean; in_draft: boolean }

export const websiteKeys = {
  all: ['website'] as const,
  sections: ['website', 'sections'] as const,
  versions: ['website', 'versions'] as const,
  projects: ['website', 'projects'] as const,
  images: ['website', 'images'] as const,
}

export const useWebsiteSections = () =>
  useQuery({ queryKey: websiteKeys.sections, queryFn: () => get<{ sections: WebsiteSection[]; latest: WebsiteVersion | null }>('/api/website/sections') })
export const useWebsiteVersions = () =>
  useQuery({ queryKey: websiteKeys.versions, queryFn: () => get<{ versions: WebsiteVersion[] }>('/api/website/versions') })
export const useWebsiteProjects = () =>
  useQuery({ queryKey: websiteKeys.projects, queryFn: () => get<{ projects: WebsiteProject[]; most_photos: number }>('/api/website/projects') })
export const useWebsiteImages = () =>
  useQuery({ queryKey: websiteKeys.images, queryFn: () => get<{ images: WebsiteImage[] }>('/api/website/images') })

export const saveDraft = (key: string, draft: unknown) => put<{ message: string }>(`/api/website/sections/${key}`, { draft })
export const discardDraft = (key: string) => post<{ message: string }>(`/api/website/sections/${key}/discard`)
export const publishWebsite = (note = '') => post<{ message: string; version: number }>('/api/website/publish', { note })
export const restoreVersion = (id: number) => post<{ message: string; version: number }>(`/api/website/versions/${id}/restore`)
export const removeImage = (id: number) => del<{ message: string }>(`/api/website/images/${id}`)

/** A picture already cropped and made small in the browser. For a project it joins the project's photos. */
export function uploadImage(blob: Blob, name: string, place: Place, jobId = 0) {
  const fd = new FormData()
  fd.append('file', blob, name)
  fd.append('place', place)
  if (jobId) fd.append('job_id', String(jobId))
  return api<{ id: number; path: string; message: string }>('/api/website/images', { method: 'POST', body: fd })
}

/** How a picture named in the website's content is shown in the panel: the site's own files from the build, an upload
 *  from the server. */
export const pictureUrl = (path: string, thumb = false) =>
  !path ? '' : path.startsWith('/api/') ? path + (thumb ? '?thumb=1' : '') : import.meta.env.BASE_URL + path

/** Where the site is, for the preview: in development the staff app owns "/", and the site is at /site. */
export const siteUrl = () => (import.meta.env.PROD ? '/' : '/site')

/** An opening on the website's Careers section: Recruitment's own job. */
export interface WebsiteOpening { id: number; reference: string; title: string; location: string; experience: string; description: string; status: string; on_website: boolean; opened_at: string; closed_at: string; applications: number }
export type OpeningInput = Pick<WebsiteOpening, 'title' | 'location' | 'experience' | 'description'>

export const useWebsiteOpenings = () =>
  useQuery({ queryKey: ['website', 'careers'], queryFn: () => get<{ openings: WebsiteOpening[] }>('/api/website/careers') })
export const postOpening = (o: OpeningInput) => post<{ message: string }>('/api/website/careers', o)
export const editOpening = (id: number, o: OpeningInput) => put<{ message: string }>(`/api/website/careers/${id}`, o)
export const closeOpening = (id: number) => post<{ message: string }>(`/api/website/careers/${id}/close`)
export const reopenOpening = (id: number) => post<{ message: string }>(`/api/website/careers/${id}/reopen`)
