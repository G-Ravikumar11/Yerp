import { useQuery } from '@tanstack/react-query'
import { api, del, get, post } from '@/lib/api'
import { shrinkImage } from './files'

export const chatKeys = { all: ['chat'] as const }

export interface ChatFile { id: number; name: string; is_image: boolean; url: string; thumb_url: string }
export interface Thread { id: number; title: string; project: string; closed: boolean; unread: number; last_message_at: string; last: { author_name: string; body: string } | null }
export interface Message { id: number; mine: boolean; author_name: string; body: string; deleted: boolean; files: ChatFile[]; created_at: string }
export interface ThreadDetail { thread: { id: number; title: string; project: string; started_by_name: string; closed: boolean }; messages: Message[] }
export interface Person { key: string; name: string; role: string }

export const useThreads = (job: number) => useQuery({ queryKey: ['chat', 'threads', job], queryFn: () => get<{ threads: Thread[]; unread: number }>(`/api/chat/threads${job ? `?job_id=${job}` : ''}`), refetchInterval: 8000 })
export const useThread = (id: number) => useQuery({ queryKey: ['chat', 'thread', id], enabled: id > 0, queryFn: () => get<ThreadDetail>(`/api/chat/threads/${id}`), refetchInterval: 8000 })
export const usePeople = () => useQuery({ queryKey: ['chat', 'people'], staleTime: 5 * 60_000, queryFn: () => get<{ people: Person[]; me: string }>('/api/chat/people') })
export const useChatUnread = () => useQuery({ queryKey: ['chat', 'unread'], queryFn: () => get<{ unread: number }>('/api/chat/unread'), refetchInterval: 60_000 })

export const startThread = (b: { job_id: number; title: string; body: string }) => post<{ thread: { id: number } }>('/api/chat/threads', b)
export const sendMessage = (thread: number, body: string, file_ids: number[]) => post<{ message?: string }>(`/api/chat/threads/${thread}/messages`, { body, file_ids })
export const removeMessage = (id: number) => del<{ message?: string }>(`/api/chat/messages/${id}`)
export const setClosed = (id: number, closed: boolean) => post<{ message: string }>(`/api/chat/threads/${id}/${closed ? 'close' : 'reopen'}`)

/** A photo or paper put with the message being written; the message names it when it is sent. */
export async function attach(thread: number, f: File): Promise<ChatFile> {
  const fd = new FormData()
  const big = await shrinkImage(f, 1600, 0.82)
  if (big) {
    fd.append('file', big, f.name.replace(/\.[^.]+$/, '') + '.jpg')
    const small = await shrinkImage(f, 360, 0.7)
    if (small) fd.append('thumb', small, 'thumb.jpg')
  } else fd.append('file', f, f.name)
  return (await api<{ file: ChatFile }>(`/api/chat/threads/${thread}/files`, { method: 'POST', body: fd })).file
}
