import { useQuery } from '@tanstack/react-query'
import { api, del, get } from '@/lib/api'

export const fileKeys = { all: ['files'] as const }

export interface FileItem {
  id: number
  job_id: number | null
  kind: 'photo' | 'drawing' | 'document' | string
  attached_type: string
  attached_id: number
  name: string
  caption: string
  size: number
  original_size: number
  shared: boolean
  taken_on: string
  uploaded_by_name: string
  is_image: boolean
  url: string
  thumb_url: string
}
export interface FileSummary { count?: number; drawings: number; photos: number; documents: number; stored_bytes: number; saved_bytes?: number; uploaders?: string[] }
export interface FileFilter { kind: string; q: string; from: string; to: string; by: string }
export const noFilter: FileFilter = { kind: '', q: '', from: '', to: '', by: '' }

export const fileQuery = (f: FileFilter) => `${f.kind ? `&kind=${encodeURIComponent(f.kind)}` : ''}${f.q ? `&q=${encodeURIComponent(f.q)}` : ''}${f.from ? `&date_from=${f.from}` : ''}${f.to ? `&date_to=${f.to}` : ''}${f.by ? `&by=${encodeURIComponent(f.by)}` : ''}`

/** The files kept against one record, filtered the way they are looked for. */
export const useFiles = (type: string, id: number, f: FileFilter) =>
  useQuery({ queryKey: ['files', type, id, f], enabled: !!type && id > 0, queryFn: () => get<{ files: FileItem[]; summary: FileSummary; locked: boolean }>(`/api/files?attached_type=${type}&attached_id=${id}${fileQuery(f)}`) })

export const removeFile = (id: number) => del<{ message?: string }>(`/api/files/${id}`)

export function fileSize(n: number | undefined) {
  if (!n) return ''
  return n >= 1048576 ? `${Math.round(n / 104857.6) / 10} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

/** A photo made smaller before it goes up: at most `max` pixels on its long side, as a JPEG. A day's pictures then cost a few hundred kilobytes. */
function shrinkImage(file: File, max: number, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return resolve(null)
    const img = new Image()
    img.onload = () => {
      const scale = Math.min(1, max / Math.max(img.width, img.height))
      const c = document.createElement('canvas')
      c.width = Math.round(img.width * scale)
      c.height = Math.round(img.height * scale)
      c.getContext('2d')?.drawImage(img, 0, 0, c.width, c.height)
      c.toBlob((b) => { URL.revokeObjectURL(img.src); resolve(b) }, 'image/jpeg', quality)
    }
    img.onerror = () => resolve(null)
    img.src = URL.createObjectURL(file)
  })
}

/** How many files go up at once. Each upload waits mostly on the round trips to the database, so a few side by side
 * finish together in about the time one took; more than this would only crowd the connection on a phone. */
const UPLOADS_AT_ONCE = 3

/** Send files against a record. Returns how many went and the reasons for any that did not (in the order chosen). */
export async function uploadFiles(files: File[], type: string, id: number, extra: Record<string, string> = {}) {
  let done = 0
  const reasons: (string | null)[] = files.map(() => null)
  let next = 0
  const worker = async () => {
    while (next < files.length) {
      const i = next++
      const reason = await uploadOne(files[i], type, id, extra)
      if (reason) reasons[i] = reason
      else done++
    }
  }
  await Promise.all(Array.from({ length: Math.min(UPLOADS_AT_ONCE, files.length) }, worker))
  return { done, failed: reasons.filter((r): r is string => r !== null) }
}

/** One file, shrunk first when it is a photograph; null when it was saved, else why not. */
async function uploadOne(f: File, type: string, id: number, extra: Record<string, string>): Promise<string | null> {
  const fd = new FormData()
  const drawing = extra.kind === 'drawing'
  let big = await shrinkImage(f, drawing ? 2400 : 1600, drawing ? 0.85 : 0.8)
  if (big && big.size >= f.size && f.type === 'image/jpeg') big = null
  if (big) {
    fd.append('file', big, f.name.replace(/\.[^.]+$/, '') + '.jpg')
    const small = await shrinkImage(f, 320, 0.6)
    if (small) fd.append('thumb', small, 'thumb.jpg')
  } else fd.append('file', f, f.name)
  fd.append('attached_type', type)
  fd.append('attached_id', String(id))
  for (const [k, v] of Object.entries(extra)) fd.append(k, v)
  try {
    await api('/api/files', { method: 'POST', body: fd })
    return null
  } catch (e) {
    return `${f.name}: ${e instanceof Error ? e.message : 'not saved'}`
  }
}
